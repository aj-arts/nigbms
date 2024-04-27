import logging
import math
import os

import hydra
import matplotlib.pyplot as plt
import numpy as np
import pytorch_lightning as pl
import torch
from hydra.utils import instantiate
from omegaconf import OmegaConf
from tensordict import TensorDict
from torch import Tensor
from torch.autograd import grad
from torch.nn.functional import cosine_similarity, mse_loss
from torch.nn.utils import clip_grad_norm_

from nigbms.modules.solvers import _Solver
from nigbms.modules.wrapper import WrappedSolver
from nigbms.utils.resolver import calc_indim

log = logging.getLogger(__name__)
OmegaConf.register_new_resolver("calc_indim", calc_indim)


#### TEST FUNCTIONS ####
def sphere(tensor):
    return torch.sum(tensor**2, dim=-1, keepdim=True)


def rosenbrock(x):
    x1 = x[..., :-1]
    x2 = x[..., 1:]
    return torch.sum(100 * (x2 - x1**2) ** 2 + (1 - x1) ** 2, dim=-1, keepdim=True)


def rosenbrock_separate(x):
    assert x.shape[-1] % 2 == 0, "Dimension must be even."
    x1 = x[..., ::2]
    x2 = x[..., 1::2]

    return torch.sum((1 - x1) ** 2 + 100 * (x2 - x1**2) ** 2, dim=-1, keepdim=True)


def rastrigin(x):
    A = 10
    n = x.shape[-1]
    return A * n + torch.sum(x**2 - A * torch.cos(x * math.pi * 2), dim=-1, keepdim=True)


class TestFunctionSolver(_Solver):
    def __init__(self, problem) -> None:
        super().__init__(params_fix={}, params_learn={"x": (problem.dim,)})
        self.f = eval(problem.test_function)

    def forward(self, tau: dict, theta: Tensor) -> Tensor:
        return self.f(theta["x"])


### PLOTTING ###
def plot_results(results, test_function, cfg):
    # draw contour lines
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))

    plot_params = {
        "f_true": {"color": "r", "alpha": 1.0},
        "f_fwd": {"color": "k", "alpha": 1.0},
        "f_hat_true": {"color": "g", "alpha": 1.0},
        "cv_fwd": {"color": "b", "alpha": 1.0},
    }
    labels = {
        "f_true": r"$\nabla f$",
        "f_fwd": r"$\mathbf{g}_\mathrm{v}$",
        "f_hat_true": r"$\nabla \hat f$",
        "cv_fwd": r"$\mathbf{h}_\mathrm{v}$",
    }
    for grad_type, steps_list in results.items():
        for i, steps in enumerate(steps_list):
            z = test_function(steps)
            ax.plot(
                np.arange(len(z)),
                z.mean(dim=1).ravel(),
                label=labels[grad_type] if i == 0 else None,
                **plot_params[grad_type],
            )
            if grad_type == "f_true":
                ax.set_ylim(z.mean(dim=1).min() * 0.1, z.mean(dim=1).max() * 10)

    ax.set_yscale("log")
    ax.legend()
    plt.savefig(
        f"{cfg.common.run_cfgs.function_name}{cfg.common.run_cfgs.dim}D.png", bbox_inches="tight", pad_inches=0.05
    )


### MAIN ###
@hydra.main(version_base="1.3", config_path="../configs/train", config_name="minimize_testfunctions")
def main(cfg):
    # set up
    torch.set_default_tensor_type(eval(cfg.problem.tensor_type))
    log.info(cfg.wrapper.grad_type)
    log.info(os.getcwd())
    pl.seed_everything(seed=cfg.seed, workers=True)
    test_function = eval(cfg.problem.test_function)
    tau = {}
    x = torch.Tensor(cfg.problem.num_samples, cfg.problem.dim).uniform_(*cfg.problem.initial_range)
    x.requires_grad = True
    theta = TensorDict({"x": x})
    solver = instantiate(cfg.solver)
    surrogate = instantiate(cfg.surrogate)
    wrapped_solver = WrappedSolver(solver, surrogate, cfg.wrapper)

    m_opt = instantiate(cfg.optimizer.m_opt, params=[theta["x"]])
    s_opt = instantiate(cfg.optimizer.s_opt, params=surrogate.parameters())
    ys = torch.zeros((cfg.problem.num_iter + 1, cfg.problem.num_samples))
    sims = torch.zeros((cfg.problem.num_iter + 1, cfg.problem.num_samples))
    ys[0] = test_function(theta.detach()).squeeze()

    for i in range(1, cfg.problem.num_iter + 1):
        m_opt.zero_grad()
        s_opt.zero_grad()

        # forward pass
        y, dvf, y_hat, dvf_hat = wrapped_solver(tau, theta)

        # compute gradient for theta
        m_loss = y.sum()
        m_loss.backward(retain_graph=True, inputs=[theta])

        # compute gradient for surrogate
        if cfg.wrapper.grad_type in ["cv_fwd", "f_hat_true"]:
            y_loss = mse_loss(y.clone().detach(), y_hat)
            dvf_loss = mse_loss(dvf.clone().detach(), dvf_hat)
            s_loss = cfg.loss.y * y_loss + cfg.loss.dvf * dvf_loss
            s_loss.backward(retain_graph=True, inputs=list(surrogate.parameters()))

        # for logging
        f_true = grad(y.sum(), theta, retain_graph=True)[0]
        if cfg.wrapper.grad_type != "f_true":
            f_fwd = dvf.sum(dim=1, keepdim=True) * v * cfg.wrapper.v_scale

            if cfg.wrapper.grad_type in ["cv_fwd", "f_hat_true"]:
                f_hat_fwd = dvf_hat.sum(dim=1, keepdim=True) * v * cfg.wrapper.v_scale
                f_hat_true = grad(y_hat.sum(), theta, retain_graph=True)[0]
                cv_fwd = f_fwd - (f_hat_fwd - f_hat_true)

        # update
        if cfg.optimizer.m_clip is not None:
            clip_grad_norm_(theta, cfg.optimizer.m_clip)
        if cfg.optimizer.s_clip is not None:
            clip_grad_norm_(surrogate.parameters(), cfg.optimizer.s_clip)
        m_opt.step()
        s_opt.step()

        # store steps
        ys[i] = y.detach().squeeze()
        sims[i] = cosine_similarity(f_true, eval(cfg.wrapper.grad_type), dim=1, eps=1e-20).detach()

        # print progress
        if i % 100 == 0:
            log.info(
                f"{i}: ymean={y.mean():.3g}, ymax={y.max():.3g}, ymed={y.median():.3g}, ymin={y.min():.3g}, sim={sims[i].mean():.3g}"
            )

    ys = ys.cpu()
    sims = sims.cpu()
    torch.save(ys, f"{cfg.problem.test_function}{cfg.problem.dim}D-{cfg.wrapper.grad_type}-y.pt")
    torch.save(sims, f"{cfg.problem.test_function}{cfg.problem.dim}D-{cfg.wrapper.grad_type}-sim.pt")


if __name__ == "__main__":
    main()
