"""
This file includes the torch models. We wrap the three
models into one class for convenience.
"""
import json

import numpy as np

import torch
from torch import nn
import torch.nn.functional as F


class Bottleneck(nn.Module):
    # 前面1x1和3x3卷积的filter个数相等，最后1x1卷积是其expansion倍
    expansion = 4

    def __init__(self, in_planes, planes, stride=1):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv1d(in_planes, planes, kernel_size=(1,), bias=False)
        self.bn1 = nn.BatchNorm1d(planes)
        self.conv2 = nn.Conv1d(planes, planes, kernel_size=(3,),
                               stride=(stride,), padding=1, bias=False)
        self.bn2 = nn.BatchNorm1d(planes)
        self.conv3 = nn.Conv1d(planes, self.expansion*planes,
                               kernel_size=(1,), bias=False)
        self.bn3 = nn.BatchNorm1d(self.expansion*planes)

        self.shortcut = nn.Sequential()
        if stride != 1 or in_planes != self.expansion*planes:
            self.shortcut = nn.Sequential(
                nn.Conv1d(in_planes, self.expansion*planes,
                          kernel_size=(1,), stride=(stride,), bias=False),
                nn.BatchNorm1d(self.expansion*planes)
            )

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = F.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        out += self.shortcut(x)
        out = F.relu(out)
        return out


# 用于ResNet18和34的残差块，用的是2个3x3的卷积
class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, in_planes, planes, stride=1):
        super(BasicBlock, self).__init__()
        self.conv1 = nn.Conv1d(in_planes, planes, kernel_size=(3,),
                               stride=(stride,), padding=1, bias=False)
        self.bn1 = nn.BatchNorm1d(planes)
        self.conv2 = nn.Conv1d(planes, planes, kernel_size=(3,),
                               stride=(1,), padding=1, bias=False)
        self.bn2 = nn.BatchNorm1d(planes)
        self.shortcut = nn.Sequential()
        # 经过处理后的x要与x的维度相同(尺寸和深度)
        # 如果不相同，需要添加卷积+BN来变换为同一维度
        if stride != 1 or in_planes != self.expansion * planes:
            self.shortcut = nn.Sequential(
                nn.Conv1d(in_planes, self.expansion * planes,
                          kernel_size=(1,), stride=(stride,), bias=False),
                nn.BatchNorm1d(self.expansion * planes)
            )

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.bn2(self.conv2(out))
        out += self.shortcut(x)
        out = F.relu(out)
        return out


class GeneralModelResnet(nn.Module):
    def __init__(self):
        super().__init__()
        self.in_planes = 82
        # input 1*54*68
        self.conv1 = nn.Conv1d(50, 82, kernel_size=(3,),
                               stride=(2,), padding=1, bias=False)  # 1*27*136

        self.bn1 = nn.BatchNorm1d(82)

        self.layer1 = self._make_layer(BasicBlock, 82, 2, stride=2)  # 1*14*82
        self.layer2 = self._make_layer(BasicBlock, 164, 2, stride=2)  # 1*7*164
        self.layer3 = self._make_layer(BasicBlock, 328, 2, stride=2)  # 1*4*328
        self.linear1 = nn.Linear(328 * BasicBlock.expansion * 4 + 19 * 2, 2048)
        self.linear2 = nn.Linear(2048, 1024)
        self.linear3 = nn.Linear(1024, 512)
        self.linear4 = nn.Linear(512, 256)
        self.linear5 = nn.Linear(256, 1)

    def _make_layer(self, block, planes, num_blocks, stride):
        strides = [stride] + [1] * (num_blocks - 1)
        layers = []
        for stride in strides:
            layers.append(block(self.in_planes, planes, stride))
            self.in_planes = planes * block.expansion
        return nn.Sequential(*layers)

    def forward(self, z, x, return_value=False, flags=None, debug=False):

        out = F.relu(self.bn1(self.conv1(z)))
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = out.flatten(1, 2)
        out = torch.cat([x, x, out], dim=-1)
        out = F.leaky_relu_(self.linear1(out))
        out = F.leaky_relu_(self.linear2(out))
        out = F.leaky_relu_(self.linear3(out))
        out = F.leaky_relu_(self.linear4(out))
        out = F.leaky_relu_(self.linear5(out))
        if return_value:
            return dict(values=out)
        else:
            if flags is not None and flags.exp_epsilon > 0 and np.random.rand() < flags.exp_epsilon:
                action = torch.randint(out.shape[0], (1,))[0]
            else:
                action = torch.argmax(out,dim=0)[0]
            return dict(action=action, max_value=torch.max(out), values=out)


class GeneralModelBid(nn.Module):
    def __init__(self):
        super().__init__()
        self.in_planes = 12
        # input 1*54*22
        self.conv1 = nn.Conv1d(6, 12, kernel_size=(3,),
                               stride=(2,), padding=1, bias=False)  # 1*27*12

        self.bn1 = nn.BatchNorm1d(12)

        self.layer1 = self._make_layer(Bottleneck, 12, 2, stride=2)  # 1*14*12
        self.layer2 = self._make_layer(Bottleneck, 24, 2, stride=2)  # 1*7*24
        self.layer3 = self._make_layer(Bottleneck, 48, 2, stride=2)  # 1*4*48
        self.linear1 = nn.Linear(48 * Bottleneck.expansion * 4, 512)
        self.linear2 = nn.Linear(512, 512)
        self.linear3 = nn.Linear(512, 512)
        self.linear4 = nn.Linear(512, 256)
        self.linear5 = nn.Linear(256, 1)

    def _make_layer(self, block, planes, num_blocks, stride):
        strides = [stride] + [1] * (num_blocks - 1)
        layers = []
        for stride in strides:
            layers.append(block(self.in_planes, planes, stride))
            self.in_planes = planes * block.expansion
        return nn.Sequential(*layers)

    def forward(self, z, x, return_value=False, flags=None, debug=False):
        out = F.relu(self.bn1(self.conv1(z)))
        out = self.layer1(out)
        out = self.layer2(out)
        out = self.layer3(out)
        out = out.flatten(1, 2)
        out = F.leaky_relu_(self.linear1(out))
        out = F.leaky_relu_(self.linear2(out))
        out = F.leaky_relu_(self.linear3(out))
        out = F.leaky_relu_(self.linear4(out))
        out = F.leaky_relu_(self.linear5(out))
        if return_value:
            return dict(values=out)
        else:
            if flags is not None and flags.exp_epsilon > 0 and np.random.rand() < flags.exp_epsilon:
                action = torch.randint(out.shape[0], (1,))[0]
            else:
                action = torch.argmax(out,dim=0)[0]
            return dict(action=action, max_value=torch.max(out), values=out)


GeneralModel = GeneralModelResnet


model_dict = {
    "first": GeneralModelBid,
    "second": GeneralModelBid,
    'third': GeneralModelBid,
    "landlord": GeneralModelResnet,
    "landlord_down": GeneralModelResnet,
    "landlord_up": GeneralModelResnet,
}


class Model:
    """
    The wrapper for the three models. We also wrap several
    interfaces such as share_memory, eval, etc.
    """
    def __init__(self, device=0):
        if not device == "cpu":
            device = 'cuda:' + str(device)
        # self.all_in_one_model = GeneralModel().to(torch.device(device))
        self.models = {
            'first': GeneralModelBid().to(torch.device(device)),
            'second': GeneralModelBid().to(torch.device(device)),
            'third': GeneralModelBid().to(torch.device(device)),
            'landlord': GeneralModelResnet().to(torch.device(device)),
            'landlord_down': GeneralModelResnet().to(torch.device(device)),
            'landlord_up': GeneralModelResnet().to(torch.device(device)),
        }

    def forward(self, position, z, x, training=False, flags=None, debug=False):
        model = self.models[position]
        return model.forward(z, x, training, flags, debug)

    def share_memory(self):
        self.models['first'].share_memory()
        self.models['second'].share_memory()
        self.models['third'].share_memory()
        self.models['landlord'].share_memory()
        self.models['landlord_down'].share_memory()
        self.models['landlord_up'].share_memory()

    def eval(self):
        self.models['first'].eval()
        self.models['second'].eval()
        self.models['third'].eval()
        self.models['landlord'].eval()
        self.models['landlord_down'].eval()
        self.models['landlord_up'].eval()

    def parameters(self, position):
        return self.models[position].parameters()

    def get_model(self, position):
        return self.models[position]

    def get_models(self):
        return self.models




class LandlordLstmModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(162, 128, batch_first=True)
        self.dense1 = nn.Linear(373 + 128, 512)
        self.dense2 = nn.Linear(512, 512)
        self.dense3 = nn.Linear(512, 512)
        self.dense4 = nn.Linear(512, 512)
        self.dense5 = nn.Linear(512, 512)
        self.dense6 = nn.Linear(512, 1)

    def forward(self, z, x, return_value=False, flags=None):
        lstm_out, (h_n, _) = self.lstm(z)
        lstm_out = lstm_out[:,-1,:]
        x = torch.cat([lstm_out,x], dim=-1)
        x = self.dense1(x)
        x = torch.relu(x)
        x = self.dense2(x)
        x = torch.relu(x)
        x = self.dense3(x)
        x = torch.relu(x)
        x = self.dense4(x)
        x = torch.relu(x)
        x = self.dense5(x)
        x = torch.relu(x)
        x = self.dense6(x)
        if return_value:
            return dict(values=x)
        else:
            if flags is not None and flags.exp_epsilon > 0 and np.random.rand() < flags.exp_epsilon:
                action = torch.randint(x.shape[0], (1,))[0]
            else:
                action = torch.argmax(x,dim=0)[0]
            return dict(action=action)

class FarmerLstmModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(162, 128, batch_first=True)
        self.dense1 = nn.Linear(484 + 128, 512)
        self.dense2 = nn.Linear(512, 512)
        self.dense3 = nn.Linear(512, 512)
        self.dense4 = nn.Linear(512, 512)
        self.dense5 = nn.Linear(512, 512)
        self.dense6 = nn.Linear(512, 1)

    def forward(self, z, x, return_value=False, flags=None):
        lstm_out, (h_n, _) = self.lstm(z)
        lstm_out = lstm_out[:,-1,:]
        x = torch.cat([lstm_out,x], dim=-1)
        x = self.dense1(x)
        x = torch.relu(x)
        x = self.dense2(x)
        x = torch.relu(x)
        x = self.dense3(x)
        x = torch.relu(x)
        x = self.dense4(x)
        x = torch.relu(x)
        x = self.dense5(x)
        x = torch.relu(x)
        x = self.dense6(x)
        if return_value:
            return dict(values=x)
        else:
            if flags is not None and flags.exp_epsilon > 0 and np.random.rand() < flags.exp_epsilon:
                action = torch.randint(x.shape[0], (1,))[0]
            else:
                action = torch.argmax(x,dim=0)[0]
            return dict(action=action)

# Model dict is only used in evaluation but not training
model_dict_douzero = {}
model_dict_douzero['landlord'] = LandlordLstmModel
model_dict_douzero['landlord_up'] = FarmerLstmModel
model_dict_douzero['landlord_down'] = FarmerLstmModel