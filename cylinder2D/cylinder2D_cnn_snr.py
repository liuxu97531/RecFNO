# -*- coding: utf-8 -*-
# @Time    : 2022/4/20 16:08
# @Author  : zhaoxiaoyu
# @File    : noaa_fno.py
import torch
import torch.nn.functional as F
import logging
import os
import sys
from torch.utils.data import DataLoader
import torch.backends.cudnn as cudnn

filename = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.append(filename)

from model.cnn import CNNRecon
from data.dataset import CylinderSNRDataset
from utils.misc import save_model, prep_experiment
from utils.options import parses
from utils.visualization import plot3x1
from utils.utils import cre

# Configure the arguments
args = parses()
args.exp = 'recon_cnn_cylinder_8_snr80'
args.epochs = 300
args.batch_size = 16
print(args)
torch.cuda.set_device(args.gpu_id)
cudnn.benchmark = True


def train():
    # Prepare the experiment environment
    tb_writer = prep_experiment(args)
    # Create figure dir
    args.fig_path = args.exp_path + '/figure'
    os.makedirs(args.fig_path, exist_ok=True)
    args.best_record = {'epoch': -1, 'loss': 1e10}

    # Build neural network
    net = CNNRecon(sensor_num=8, fc_size=(7, 12)).cuda()

    # Build data loader
    train_dataset = CylinderSNRDataset(index=[i for i in range(3500)], snr=True, SNRdB=80)
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, num_workers=4, shuffle=True)
    val_dataset = CylinderSNRDataset(index=[i for i in range(3500, 4250)], snr=True, SNRdB=80)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, num_workers=4)

    # Build optimizer
    optimizer = torch.optim.Adam(net.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.98)

    for epoch in range(args.epochs):
        # Training procedure
        train_loss, train_num = 0., 0.
        for i, (inputs, outputs) in enumerate(train_loader):
            inputs, outputs = inputs.cuda(), outputs.cuda()
            pre = net(inputs)
            loss = F.l1_loss(outputs, pre)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            # Record results by tensorboard
            tb_writer.add_scalar('train_loss', loss, i + epoch * len(train_loader))
            train_loss += loss.item() * inputs.shape[0]
            train_num += inputs.shape[0]

        train_loss = train_loss / train_num
        logging.info("Epoch: {}, Avg_loss: {}".format(epoch, train_loss))
        scheduler.step()

        # Validation procedure
        if epoch % args.val_interval == 0:
            net.eval()
            val_loss, val_num = 0., 0.
            for i, (inputs, outputs) in enumerate(val_loader):
                inputs, outputs = inputs.cuda(), outputs.cuda()
                with torch.no_grad():
                    pre = net(inputs)
                loss = F.l1_loss(outputs, pre)

                val_loss += loss.item() * inputs.shape[0]
                val_num += inputs.shape[0]

            # Record results by tensorboard
            val_loss = val_loss / val_num
            tb_writer.add_scalar('val_loss', val_loss, epoch)
            logging.info("Epoch: {}, Val_loss: {}".format(epoch, val_loss))
            if val_loss < args.best_record['loss']:
                save_model(args, epoch, val_loss, net)
            net.train()

            # Plotting
            if epoch % args.plot_freq == 0:
                plot3x1(outputs[-1, 0, :, :].cpu().numpy(), pre[-1, 0, :, :].cpu().numpy(),
                        file_name=args.fig_path + f'/epoch{epoch}.png')


def test(index):
    import numpy as np
    from utils.visualization import plot_results
    from model.fno import FNORecon
    from model.mlp import MLP
    from data.dataset import CylinderPodSNRDataset
    from data.dataset import CylinderObserveSNRDataset
    from data.dataset import CylinderInterpolSNRDataset
    from model.cnn import UNet
    from model.fno import VoronoiFNO2d

    # Path of trained network
    args.snapshot = '/home/ubuntu/zhaoxiaoyu/ARE/field_recon/cylinder2D/logs/ckpt/recon_fno_regre_cylinder_8/best_epoch_298_loss_0.00013076.pth'

    # Define data loader
    # test_dataset = CylinderDataset(index=[4500])
    test_dataset = CylinderObserveSNRDataset(index=index, snr=True, SNRdB=10, test=True)
    # test_dataset = CylinderInterpolSNRDataset(index=index, snr=True, SNRdB=80, test=True)
    # test_dataset = CylinderSNRDataset(index=index, snr=True, SNRdB=80, test=True)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, num_workers=0)

    # Load trained network
    # net = CNNRecon(sensor_num=8, fc_size=(7, 12)).cuda()
    net = VoronoiFNO2d(modes1=32, modes2=32, width=32, in_channels=3).cuda()
    # net = UNet(in_channels=3, out_channels=1).cuda()
    # net = FNORecon(sensor_num=8, fc_size=(7, 12), out_size=(112, 192), modes1=24, modes2=24, width=32).cuda()
    net.load_state_dict(torch.load(args.snapshot)['state_dict'])
    print('load models: ' + args.snapshot)

    # Test procedure
    net.eval()
    test_mae, test_rmse, test_num = 0.0, 0.0, 0.0
    test_max_ae = 0
    for i, (inputs, outputs) in enumerate(test_loader):
        inputs, outputs = inputs.cuda(), outputs.cuda()
        with torch.no_grad():
            pre = net(inputs)
        test_num += inputs.shape[0]
        test_mae += F.l1_loss(outputs, pre).item() * inputs.shape[0]
        test_rmse += torch.sum(cre(outputs, pre, 2)).item()
        test_max_ae += torch.sum(torch.max(torch.abs(outputs - pre).flatten(1), dim=1)[0]).item()
    print('test mae:', test_mae / test_num)
    print('test rmse:', test_rmse / test_num)
    print('test max_ae:', test_max_ae / test_num)


if __name__ == '__main__':
    # train()
    # test(index=[i for i in range(0, 3500)])
    # test(index=[i for i in range(3500, 4250)])
    test(index=[i for i in range(4250, 5000)])