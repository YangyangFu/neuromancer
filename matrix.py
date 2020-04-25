import torch
import torch.nn as nn


class SoftOrthogonal(nn.Module):
    """
    an orthogonal matrix Q (weight) is a square matrix whose columns and rows are orthogonal unit vectors (orthonormal vectors).
    Q*Q^T = Q^T*Q = I
    return transformation: Q*x
    orthogonality error to be penalized in the loss: err = ||I - Q*Q^T||^2 + ||I - Q^T*Q||^2
    https://en.wikipedia.org/wiki/Orthogonal_matrix
    """

    def __init__(self, insize):
        super().__init__()
        self.weight = nn.Parameter(torch.eye(insize, insize) + 0.01 * torch.randn(insize, insize))  # identity matrix with small noise
        self.insize = insize

    def forward(self):
        OrthoError = torch.norm(torch.norm(torch.eye(self.insize).to(self.weight.device) - torch.mm(self.weight, torch.t(self.weight)), 2) + torch.norm(
            torch.eye(self.insize).to(self.weight.device) - torch.mm(torch.t(self.weight), self.weight), 2), 2)
        return OrthoError


class InvertibleLinear(nn.Module):
    """
    an invertible matrix is a square matrix A (weight), for which following holds:
    A*B = B*A = I
    return transformation: A*x
    invertibility error to be penalized in the loss: err = ||I - A*B||^2 + ||I - B*A ||^2
    https://en.wikipedia.org/wiki/Invertible_matrix
    """

    def __init__(self, insize):
        super().__init__()
        self.weight = nn.Parameter(torch.eye(insize, insize) + 0.01 * torch.randn(insize, insize))  # identity matrix with small noise
        self.B = nn.Parameter(torch.eye(insize, insize) + 0.01 * torch.randn(insize, insize))  # identity matrix with small noise
        self.insize = insize

    def forward(self):
        OrthoError = torch.norm(torch.norm(torch.eye(self.insize).to(self.weight.device) - torch.mm(self.weight, self.B), 2) + torch.norm(
            torch.eye(self.insize).to(self.weight.device) - torch.mm(self.B, self.weight), 2), 2)
        return OrthoError