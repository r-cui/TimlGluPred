# https://github.com/locuslab/TCN/blob/master/TCN/tcn.py

import gin
import torch
import torch.nn as nn

from torch import Tensor
from torch.nn.utils import weight_norm


def seqconv(horizon_len: int):
    return SeqConv(horizon_len)


class Chomp1d(nn.Module):
    def __init__(self, chomp_size):
        super(Chomp1d, self).__init__()
        self.chomp_size = chomp_size

    def forward(self, x):
        return x[:, :, :-self.chomp_size].contiguous()


class TemporalBlock(nn.Module):
    def __init__(self, n_inputs, n_outputs, kernel_size, stride, dilation, padding, dropout=0.2):
        super(TemporalBlock, self).__init__()
        self.conv1 = weight_norm(nn.Conv1d(n_inputs, n_outputs, kernel_size,
                                           stride=stride, padding=padding, dilation=dilation))
        self.chomp1 = Chomp1d(padding)
        self.relu1 = nn.ReLU()
        self.dropout1 = nn.Dropout(dropout)

        self.conv2 = weight_norm(nn.Conv1d(n_outputs, n_outputs, kernel_size,
                                           stride=stride, padding=padding, dilation=dilation))
        self.chomp2 = Chomp1d(padding)
        self.relu2 = nn.ReLU()
        self.dropout2 = nn.Dropout(dropout)

        self.net = nn.Sequential(self.conv1, self.chomp1, self.relu1, self.dropout1,
                                 self.conv2, self.chomp2, self.relu2, self.dropout2)
        self.downsample = nn.Conv1d(n_inputs, n_outputs, 1) if n_inputs != n_outputs else None
        self.relu = nn.ReLU()
        self.init_weights()

    def init_weights(self):
        self.conv1.weight.data.normal_(0, 0.01)
        self.conv2.weight.data.normal_(0, 0.01)
        if self.downsample is not None:
            self.downsample.weight.data.normal_(0, 0.01)

    def forward(self, x):
        out = self.net(x)
        res = x if self.downsample is None else self.downsample(x)
        return self.relu(out + res)


class TemporalConvNet(nn.Module):
    def __init__(self, num_inputs, num_channels, kernel_size=2, dropout=0.2):
        super(TemporalConvNet, self).__init__()
        layers = []
        num_levels = len(num_channels)
        for i in range(num_levels):
            dilation_size = 2 ** i
            in_channels = num_inputs if i == 0 else num_channels[i-1]
            out_channels = num_channels[i]
            layers += [TemporalBlock(in_channels, out_channels, kernel_size, stride=1, dilation=dilation_size,
                                     padding=(kernel_size-1) * dilation_size, dropout=dropout)]

        self.network = nn.Sequential(*layers)

    def forward(self, x):
        x = torch.permute(x, (0, 2, 1))
        return torch.permute(self.network(x), (0, 2, 1))


class SeqConv(nn.Module):
    def __init__(self, horizon_len: int):
        super(SeqConv, self).__init__()
        layer_size = 64
        n_layer = 3
        self.horizon_len = horizon_len
        num_channels = [layer_size] * n_layer
        self.encoder = TemporalConvNet(1, num_channels)
        self.decoder = TemporalConvNet(num_channels[-1], num_channels)
        self.linear = nn.Linear(layer_size, 1)

    def forward(self, x: Tensor, x_time: Tensor, y_time: Tensor) -> Tensor:
        res = []
        for _ in range(self.horizon_len):
            x_clone = x.clone().detach()
            h = self.encoder(x_clone)
            y_hat = self.linear(self.decoder(h))
            x[:, :-1] = x_clone[:, 1:]
            x[:, -1] = y_hat[:, -1]
            res.append(y_hat[:, -1])
        res = torch.stack(res, dim=1)
        return res
