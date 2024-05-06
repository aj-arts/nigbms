# %%
import hydra
import torch
import wandb
from hydra.utils import instantiate
from lightning import LightningModule, Trainer, seed_everything
from omegaconf import DictConfig, OmegaConf
from pytorch_lightning.loggers.wandb import WandbLogger

from nigbms.utils.resolver import calc_in_channels, calc_in_dim

OmegaConf.register_new_resolver("calc_in_dim", calc_in_dim)
OmegaConf.register_new_resolver("calc_in_channels", calc_in_channels)


# %%
class NIGBMS(LightningModule):
    def __init__(self, cfg):
        super().__init__()
        self.automatic_optimization = False

        self.cfg = cfg
        self.meta_solver = instantiate(cfg.meta_solver)
        self.solver = instantiate(cfg.solver)
        self.surrogate = instantiate(cfg.surrogate)
        self.wrapped_solver = instantiate(cfg.wrapper, solver=self.solver, surrogate=self.surrogate)
        self.loss = instantiate(cfg.loss)

    def on_fit_start(self):
        seed_everything(seed=self.cfg.seed, workers=True)

    # def forward(self, tau: Task):
    #     theta = self.meta_solver(tau)
    #     y = self.wrapper(tau, theta)
    #     return y

    def _add_prefix(self, d, prefix):
        return dict([(prefix + k, v) for k, v in d.items()])

    def training_step(self, batch, batch_idx):
        opt = self.optimizers()
        opt.zero_grad()
        tau = batch
        theta = self.meta_solver(tau)
        y = self.wrapped_solver(tau, theta)
        loss = self.loss(tau, theta, y)
        self.manual_backward(loss, create_graph=True, inputs=[self.meta_solver.parameters()])
        opt.step()

    def validation_step(self, batch, batch_idx):
        tau = batch
        theta = self.meta_solver(tau)
        y = self.solver(tau, theta)  # no surrogate
        loss = self.loss(tau, theta, y)

        self.log("val/loss", loss)

    def test_step(self, batch, batch_idx, dataloader_idx):
        tau = batch
        theta = self.meta_solver(tau)
        y = self.solver(tau, theta)  # no surrogate
        loss = self.loss(tau, theta, y)

        self.log("test/loss", loss)

    def configure_optimizers(self):
        opt = instantiate(self.cfg.optimizers.opt, params=self.meta_solver.parameters())
        sch = instantiate(self.cfg.optimizers.sch, optimizer=opt)

        return {
            "optimizer": opt,
            "lr_scheduler": sch,
            "monitor": self.cfg.optimizers.monitor,
        }


@hydra.main(version_base="1.3", config_path="../configs/train", config_name="poisson1d")
def main(cfg: DictConfig):
    wandb.config = OmegaConf.to_container(cfg, resolve=True, throw_on_missing=True)
    wandb.init(project=cfg.wandb.project, config=wandb.config, mode=cfg.wandb.mode)
    logger = WandbLogger(settings=wandb.Settings(start_method="thread"))

    torch.set_default_tensor_type(torch.cuda.DoubleTensor)
    seed_everything(seed=cfg.seed, workers=True)

    callbacks = [instantiate(c) for c in cfg.callbacks]
    data_module = instantiate(cfg.data)

    nigbms = NIGBMS(cfg)

    trainer = Trainer(logger=logger, callbacks=callbacks, **cfg.trainer)
    trainer.fit(model=nigbms, datamodule=data_module)

    # TEST
    if cfg.test:
        trainer.test(ckpt_path="best", datamodule=data_module)


# %%
if __name__ == "__main__":
    main()

# %%
