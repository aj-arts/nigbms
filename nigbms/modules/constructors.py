# %%
import numpy as np
import torch
from hydra.utils import instantiate
from tensordict import TensorDict
from torch import Tensor
from torch.nn import Module
from torch.nn import functional as F


class ThetaConstructor(Module):
    def __init__(self, params):
        super().__init__()
        self.params = params
        self.encdecs = {k: instantiate(v.encdec) for k, v in self.params.items() if hasattr(v, "encdec")}

    def forward(self, theta: Tensor) -> TensorDict:
        theta_dict = TensorDict({})
        idx = 0
        for k, v in self.params.items():
            if k in self.encdecs:
                enc_dim = self.encdecs[k].enc_dim
                param = self.encdecs[k].decode(theta[:, idx : idx + enc_dim])
            else:
                enc_dim = np.prod(v.shape)
                param = theta[:, idx : idx + enc_dim]
            theta_dict[k] = param.reshape(-1, *v.shape)
            idx += enc_dim
        theta_dict["enc"] = theta.unsqueeze(-1)
        return theta_dict


class _Decoder(Module):
    def __init__(self, enc_dim: int, dec_dim) -> None:
        super().__init__()
        self.enc_dim = enc_dim
        self.dec_dim = dec_dim

    def forward(self, x: Tensor) -> Tensor:
        raise NotImplementedError


class SinEncDec(_Decoder):
    def __init__(self, enc_dim: int = 128, dec_dim: int = 128):
        super().__init__(enc_dim, dec_dim)
        self.basis = torch.sin(
            torch.arange(1, enc_dim + 1).unsqueeze(-1)
            * torch.tensor([i / (dec_dim + 1) for i in range(1, dec_dim + 1)])
            * torch.pi
        )
        self.basis = self.basis.unsqueeze(0)  # (1, dec_dim, enc_dim)
        self.basis = self.basis.cuda()

    def encode(self, decoded_theta: Tensor) -> Tensor:
        decoded_theta = decoded_theta.reshape(-1, self.dec_dim, 1)
        encoded_theta = torch.matmul(self.basis, decoded_theta)
        return encoded_theta

    def decode(self, encoded_theta: Tensor) -> Tensor:
        encoded_theta = encoded_theta.reshape(-1, self.dec_dim, 1)
        decoded_theta = torch.matmul(self.basis.transpose(1, 2), encoded_theta)  # (bs, out_dim, 1)
        return decoded_theta


class SinDecoder(_Decoder):
    def __init__(self, enc_dim: int = 128, dec_dim: int = 128):
        super().__init__(enc_dim, dec_dim)
        self.basis = torch.sin(
            torch.arange(1, dec_dim + 1).unsqueeze(-1)
            * torch.tensor([i / (dec_dim + 1) for i in range(1, dec_dim + 1)])
            * torch.pi
        )
        self.basis = self.basis.unsqueeze(0)  # (1, out_dim, n_basis)
        self.basis = self.basis.cuda()

    def forward(self, theta: Tensor) -> Tensor:
        decoded_theta = torch.matmul(self.basis, theta.unsqueeze(-1))  # (bs, out_dim, 1)
        return decoded_theta.squeeze()


class SinEncoder(_Decoder):
    def __init__(self, enc_dim: int = 128, dec_dim: int = 128):
        super().__init__(enc_dim, dec_dim)
        self.basis = torch.sin(
            torch.arange(1, dec_dim + 1).unsqueeze(-1)
            * torch.tensor([i / (dec_dim + 1) for i in range(1, dec_dim + 1)])
            * torch.pi
        )
        self.basis = self.basis.unsqueeze(0)  # (1, out_dim, n_basis)
        self.basis = self.basis.cuda()

    def forward(self, signal: Tensor) -> Tensor:
        freq_signal = torch.matmul(self.basis.transpose(1, 2), signal.reshape(-1, self.dec_dim, 1))

        return freq_signal.squeeze()


class InterpolateDecoder(Module):
    def __init__(self, out_dim: int = 32, mode="linear"):
        super().__init__()
        self.out_dim = out_dim
        self.mode = mode

    def forward(self, x: Tensor) -> Tensor:
        x = x.unsqueeze(1)
        scale_factor = self.out_dim // x.shape[-1]
        interpolated_signal = F.interpolate(x, scale_factor=scale_factor, mode=self.mode, align_corners=True)

        return interpolated_signal.squeeze(1)


class InterpolateDecoder2D(Module):
    def __init__(self, out_dim: int = 32, mode="bilinear"):
        super().__init__()
        self.out_dim = out_dim
        self.mode = mode

    def forward(self, signal: Tensor) -> Tensor:
        bs, n2 = signal.shape
        n = int(n2**0.5)
        signal = signal.reshape(bs, 1, n, n)
        scale_factor = self.out_dim // n
        interpolated_signal = F.interpolate(signal, scale_factor=scale_factor, mode=self.mode, align_corners=True)

        return interpolated_signal.reshape(bs, -1)


class FFTEncoder(Module):
    def __init__(self, out_dim: int = 32):
        super().__init__()
        self.out_dim = out_dim

    def forward(self, signal: Tensor) -> Tensor:
        freq_signal = torch.fft.rfft(signal, dim=-1)[..., : self.out_dim // 2]
        freq_signal = torch.view_as_real(freq_signal).reshape(-1, self.out_dim)
        return freq_signal


class IFFTDecoder(Module):
    def __init__(self, out_dim: int = 128):
        super().__init__()
        self.out_dim = out_dim

    def forward(self, freq_signal: Tensor) -> Tensor:
        n_components = freq_signal.shape[-1] // 2
        freq_signal = torch.view_as_complex(freq_signal.reshape(-1, n_components, 2))
        signal = torch.fft.irfft(freq_signal, n=self.out_dim, dim=-1)
        return signal


# %%