import torch
import torchvision
import numpy as np
import os
import sys
import argparse
import torch.nn.functional as F
from my_model import Feature_extract, FC_pooling
import data_utils.ShapeNetDataLoader
from model.pointnet import PointNetCls
from data_prepare import parts_loader, FC_input_loader
from torch.autograd import Variable
from utils_x_lzr import element_wise_max, element_wise_min, element_wise_mean, test_cls, save_checkpoint, to_2048
import datetime
from torch.utils.data import Dataset
import torch.nn.parallel
import logging
from pathlib import Path
from tqdm import tqdm
from model.pointnet2 import PointNet2ClsMsg
from model.pointnet import PointNetCls, feature_transform_reguliarzer


seg_classes = {'Earphone': [16, 17, 18], 'Motorbike': [30, 31, 32, 33, 34, 35], 'Rocket': [41, 42, 43],
               'Car': [8, 9, 10, 11], 'Laptop': [28, 29], 'Cap': [6, 7], 'Skateboard': [44, 45, 46], 'Mug': [36, 37],
               'Guitar': [19, 20, 21], 'Bag': [4, 5], 'Lamp': [24, 25, 26, 27], 'Table': [47, 48, 49],
               'Airplane': [0, 1, 2, 3], 'Pistol': [38, 39, 40], 'Chair': [12, 13, 14, 15], 'Knife': [22, 23]}
seg_label_to_cat = {}  # {0:Airplane, 1:Airplane, ...49:Table}
for cat in seg_classes.keys():
    for label in seg_classes[cat]:
        seg_label_to_cat[label] = cat

def parse_args():
    parser = argparse.ArgumentParser('FC of the net')
    parser.add_argument('--batchsize', type=int, default=1, help='input batch size')
    parser.add_argument('--train_metric', type=str, default=False, help='whether evaluate on training dataset')
    parser.add_argument('--workers', type=int, default=8, help='number of data loading workers')
    parser.add_argument('--epoch', type=int, default=400, help='number of epochs for training')
    parser.add_argument('--pretrain', type=str,
                         default=None,   # 模型的地址
                        help='whether use pretrain model')
    parser.add_argument('--gpu', type=str, default='0', help='specify gpu device')
    parser.add_argument('--model_name', type=str, default='FC_pooling', help='Name of model')
    parser.add_argument('--learning_rate', type=float, default=0.001, help='learning rate for training')
    parser.add_argument('--decay_rate', type=float, default=1e-4, help='weight decay')
    parser.add_argument('--optimizer', type=str, default='Adam', help='type of optimizer')
    parser.add_argument('--multi_gpu', type=str, default='0,1', help='whether use multi gpu training')
    parser.add_argument('--jitter', default=False, help="randomly jitter point cloud")
    parser.add_argument('--step_size', type=int, default=20, help="randomly rotate point cloud")

    return parser.parse_args()

args = parse_args()
experiment_dir = Path('./stage3_experiment/')
experiment_dir.mkdir(exist_ok=True)
checkpoints_dir = Path('./stage3_experiment/checkpoints_mean/')   #
checkpoints_dir.mkdir(exist_ok=True)
log_dir = Path('./stage3_experiment/logs_mean/')    #
log_dir.mkdir(exist_ok=True)

norm = True
train_root = '/home/dh/zdd/Lzr/instance_seg/train'   # modify it to shapenet dataset
test_root = '/home/dh/zdd/Lzr/instance_seg/test'   # modify it to shapenet dataset
model_path = 'shape_pointnet2-0.989931-0183.pth'
# extract feature using Feature_extract.
train_set = parts_loader(train_root)   # use shapenetloader, in ../data_utils
trainloader = torch.utils.data.DataLoader(train_set, batch_size=args.batchsize, shuffle=True, num_workers=int(args.workers))
test_set = parts_loader(test_root)   # use shapenetloader, in ../data_utils
testloader = torch.utils.data.DataLoader(test_set, batch_size=args.batchsize, shuffle=False, num_workers=int(args.workers))

model1 = Feature_extract()
#model3 = PointNetCls()

if args.multi_gpu is not None:
    device_ids = [int(x) for x in args.multi_gpu.split(',')]
    torch.backends.cudnn.benchmark = True
    model1.cuda(device_ids[0])
    model1 = torch.nn.DataParallel(model1, device_ids=device_ids)
#    model3.cuda(device_ids[0])
#    model3 = torch.nn.DataParallel(model1, device_ids=device_ids)
else:
    model1.cuda()
#    model3.cuda()
model1.load_state_dict(torch.load(model_path), strict=False)   #加入特征提取模型的path
#model3.load_state_dict(torch.load(''), strict=False)

#features_train = []
time = str(datetime.datetime.now())
os.makedirs('/home/dh/zdd/Lzr/stage3_full/train')
for batchid, (points, norms, labels) in tqdm(enumerate(trainloader, 0), total=len(trainloader), smoothing=0.9):
    #    batchsize, num_point, _ = points.size()
    features_train = []
    for part in points:
        part = np.array(part)
        part = to_2048(part)
        part = torch.Tensor(part)
        part = part.permute(1, 2, 0)
#        print(part.shape)
#        norm.transpose(2, 1)
        part, labels = Variable(part).cuda(), Variable(
            labels.long()).cuda()
        model1 = model1.eval()
#        np.savez('/home/dh/zdd/Lzr/save', part.cpu().numpy())
        _, feature = model1(part)
        feature = feature.view(1, 1024)
        features_train.append(feature.cpu().detach().numpy())
    output = element_wise_min(features_train)
    np.savez('/home/dh/zdd/Lzr/stage3_full/train' + '/'+str(batchid)+'.npz',
             feature=output, cls=labels.cpu().detach().numpy())

os.makedirs('/home/dh/zdd/Lzr/stage3_full/test')
#feat_test = []
for batchid, (points, norms, labels) in tqdm(enumerate(testloader, 0), total=len(testloader), smoothing=0.9):
    #    batchsize, num_point, _ = points.size()
    feat_test = []
    for part in points:
        part = np.array(part)
        part = to_2048(part)
        part = torch.Tensor(part)
        part = part.permute(1, 2, 0)
#        part.transpose(2, 1)
#        norm.transpose(2, 1)
        part, labels = Variable(part).cuda(), Variable(
            labels.long()).cuda()
        model1 = model1.eval()
        _, feature = model1(part)
        feature = feature.view(1, 1024)
        feat_test.append(feature.cpu().detach().numpy())
    output = element_wise_min(feat_test)
    np.savez('/home/dh/zdd/Lzr/stage3_full/test'+'/'+str(batchid)+'.npz',
            feature=output, cls=labels.cpu().detach().numpy())

# training FC_pooling
logger = logging.getLogger("FC_layer training")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler('./stage3_experiment/logs_mean/train_%s_' % args.model_name + str(datetime.datetime.now().strftime('%Y-%m-%d %H-%M'))+'.txt')  #
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
logger.info('---------------------------------------------------TRANING---------------------------------------------------')
logger.info('PARAMETER ...')
logger.info(args)

feature_train_path = '/home/dh/zdd/Lzr/stage3_mean/train'  #
feature_test_path = '/home/dh/zdd/Lzr/stage3_mean/test'  #
train_data = FC_input_loader(feature_train_path)
traindataloader = torch.utils.data.DataLoader(train_data, batch_size=64, shuffle=True)
test_data = FC_input_loader(feature_test_path)
testdataloader = torch.utils.data.DataLoader(test_data, batch_size=64, shuffle=False)

model2 = torch.nn.Sequential(
    torch.nn.Linear(1024, 256),
    torch.nn.BatchNorm1d(256),
    torch.nn.ReLU(),
    torch.nn.Dropout(p=0.5),
    torch.nn.Linear(256, 64),
    torch.nn.BatchNorm1d(64),
    torch.nn.ReLU(),
    torch.nn.Dropout(p=0.5),
    torch.nn.Linear(64, 16)
)
if args.pretrain is not None:
    print('Use pretrain model...')
    logger.info('Use pretrain model')
    checkpoint = torch.load(args.pretrain)
    start_epoch = checkpoint['epoch']
    model2.load_state_dict(checkpoint['model_state_dict'])
else:
    print('No existing model, starting training from scratch...')
    start_epoch = 0
if args.multi_gpu is not None:
    device_ids = [int(x) for x in args.multi_gpu.split(',')]
    torch.backends.cudnn.benchmark = True
    model2.cuda(device_ids[0])
    model2 = torch.nn.DataParallel(model2, device_ids=device_ids)
else:
    model2.cuda()

if args.optimizer == 'SGD':
    optimizer = torch.optim.SGD(model2.parameters(), lr=0.01, momentum=0.9)
elif args.optimizer == 'Adam':
    optimizer = torch.optim.Adam(
        model2.parameters(),
        lr=args.learning_rate,
        betas=(0.9, 0.999),
        eps=1e-08,
        weight_decay=args.decay_rate
    )
scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)
start_epoch = 0
global_epoch = 0
global_step = 0
best_tst_accuracy = 0.0
blue = lambda x: '\033[94m' + x + '\033[0m'

#TRANING

logger.info('Start training...')
for epoch in range(start_epoch, args.epoch):
    print('Epoch %d (%d/%s):' % (global_epoch + 1, epoch + 1, args.epoch))
    logger.info('Epoch %d (%d/%s):', global_epoch + 1, epoch + 1, args.epoch)

    scheduler.step()
    for batch_id, data in tqdm(enumerate(traindataloader, 0), total=len(traindataloader), smoothing=0.9):
        feat, cls = data
        feat, cls = Variable(feat.cuda()), Variable(cls.cuda())
#        feat = feat.transpose(2, 1)
        optimizer.zero_grad()
        model2 = model2.train()
        pred = model2(feat)
        loss = torch.nn.CrossEntropyLoss()(pred, cls.long())
        loss.backward()
        optimizer.step()
        global_step += 1

    test_acc = test_cls(model2.eval(), testdataloader) #if args.train_metric else None
    #acc = test(model2, testdataloader)

    print('\r Loss: %f' % loss.data)
    logger.info('Loss: %.2f', loss.data)
    if args.train_metric:
        print('Train Accuracy: %f' % test_acc)
        logger.info('Train Accuracy: %f', test_acc)
    print('\r Test %s: %f' % (blue('Accuracy'), test_acc))
    logger.info('Test Accuracy: %f', test_acc)

    if (test_acc >= best_tst_accuracy) and epoch > 5:
        best_tst_accuracy = test_acc
        logger.info('Save model...')
        save_checkpoint(
            global_epoch + 1,
            test_acc if args.train_metric else 0.0,
            test_acc,
            model2,
            optimizer,
            str(checkpoints_dir),
            args.model_name)
        print('Saving model....')
    global_epoch += 1
print('Best Accuracy: %f' % best_tst_accuracy)

logger.info('End of training...')
