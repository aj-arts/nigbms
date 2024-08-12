import pytest
import torch
from petsc4py import PETSc

from nigbms.modules.tasks import PETScLinearSystemTask, PyTorchLinearSystemTask, petsc2torch, torch2petsc


@pytest.fixture
def petsc_task():
    A = PETSc.Mat().createAIJ([3, 3])
    A.setUp()
    A[0, 0] = 1.0
    A[1, 1] = 2.0
    A[2, 2] = 3.0
    A.assemble()

    b = PETSc.Vec().createSeq(3)
    b.setArray([1.0, 2.0, 3.0])

    return PETScLinearSystemTask(params=None, A=A, b=b, x=None, rtol=1.0e-6, maxiter=100)


@pytest.fixture
def torch_task():
    A = torch.tensor([[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]], dtype=torch.float64)
    b = torch.tensor([1.0, 2.0, 3.0], dtype=torch.float64)
    rtol = torch.tensor(1.0e-6)
    maxiter = torch.tensor(100)
    return PyTorchLinearSystemTask(params=None, A=A, b=b, x=None, rtol=rtol, maxiter=maxiter)


def test_petsc2torch(petsc_task, torch_task):
    assert torch_task == petsc2torch(petsc_task)


def test_torch2petsc(torch_task, petsc_task):
    assert petsc_task == torch2petsc(torch_task)
