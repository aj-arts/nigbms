from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import torch
from petsc4py import PETSc
from torch import Tensor, sparse_csr_tensor, tensor


@dataclass
class TaskParams:
    """Parameters to generate a task"""

    pass


@dataclass
class Task:
    """Base class for tasks"""

    params: TaskParams = None


@dataclass
class MinimizeTestFunctionTask(Task):
    f: Callable = None  # Test function to minimize


@dataclass
class LinearSystemTask(Task):
    A: Any = None
    b: Any = None
    x: Any = None  # Ground Truth if applicable, otherwise the solution provided by the solver
    rtol: Any = None
    maxiter: Any = None


@dataclass
class PyTorchLinearSystemTask(LinearSystemTask):
    A: Tensor = None  # Dense matrix
    b: Tensor = None
    x: Tensor = None  # Ground Truth if applicable, otherwise the solution provided by the solver
    rtol: Tensor = None
    maxiter: Tensor = None

    def __eq__(self, other):
        return (
            torch.equal(self.A, other.A)
            and torch.equal(self.b, other.b)
            and ((self.x is None and other.x is None) or torch.equal(self.x, other.x))
            and torch.equal(self.rtol, other.rtol)
            and torch.equal(self.maxiter, other.maxiter)
        )


@dataclass
class PETScLinearSystemTask(LinearSystemTask):
    A: PETSc.Mat = None  # Sparse matrix (AIJ)
    b: PETSc.Vec = None
    x: PETSc.Vec = None  # Ground Truth if applicable, otherwise the solution provided by the solver
    rtol: float = None
    maxiter: int = None
    problem: Any = None  # This is a placeholder for the problem object to keep it alive TODO: remove this

    def __eq__(self, other):
        return (
            self.A.equal(other.A)
            and self.b.equal(other.b)
            and ((self.x is None and other.x is None) or self.x.equal(other.x))
            and np.isclose(self.rtol, other.rtol)  # can't use == for float
            and self.maxiter == other.maxiter
        )


@dataclass
class OpenFOAMTask:
    u: Any = None
    p: Any = None


def petsc2torch(task: PETScLinearSystemTask) -> PyTorchLinearSystemTask:
    size = task.A.getSize()
    row_idx, col_idx, values = task.A.getValuesCSR()
    A = sparse_csr_tensor(row_idx, col_idx, values, size).to_dense()

    return PyTorchLinearSystemTask(
        params=task.params,
        A=A,
        b=tensor(task.b.getArray()),
        x=tensor(task.x.getArray()) if task.x is not None else None,
        rtol=tensor(task.rtol),
        maxiter=tensor(task.maxiter),
    )


# TODO: check this function (Copilot generated)
def torch2petsc(task: PyTorchLinearSystemTask) -> PETScLinearSystemTask:
    A_sp = task.A.cpu().to_sparse_csr()
    A = PETSc.Mat().createAIJ(size=A_sp.shape, nnz=A_sp._nnz())
    A.setValuesCSR(
        I=A_sp.crow_indices().numpy().astype("int32"),
        J=A_sp.col_indices().numpy().astype("int32"),
        V=A_sp.values().numpy(),
    )
    A.assemble()
    b = PETSc.Vec().createWithArray(task.b.numpy())
    x = PETSc.Vec().createWithArray(task.x.numpy()) if task.x is not None else None
    return PETScLinearSystemTask(A=A, b=b, x=x, rtol=float(task.rtol), maxiter=int(task.maxiter))
