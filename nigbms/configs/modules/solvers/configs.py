# %%
from dataclasses import dataclass

from hydra.core.config_store import ConfigStore
from omegaconf import DictConfig

cs = ConfigStore.instance()


@dataclass
class PETScKSPConfig:
    _target_: str = "nigbms.modules.solvers.PETScKSP"
    params_fix: DictConfig = DictConfig({"history_length": 100})
    params_learn: DictConfig = DictConfig({})
    debug: bool = True


cs.store(name="petsc_ksp_default", node=PETScKSPConfig)


@dataclass
class PyTorchJacobiConfig:
    _target_: str = "nigbms.modules.solvers.PyTorchJacobi"
    params_fix: DictConfig = DictConfig({"history_length": 100})
    params_learn: DictConfig = DictConfig({})


cs.store(name="pytorch_jacobi_default", node=PyTorchJacobiConfig)