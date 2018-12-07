import argparse, json
import torch
import torch.nn as nn
import torch.optim as optim
from tensorboardX import SummaryWriter
from torch.autograd import Variable
from torch.nn.utils.rnn import pack_padded_sequence
from torchvision import transforms

from dataset import ImageCaptionDataset
from decoder import Decoder
from encoder import Encoder
from utils import AverageMeter, accuracy


data_transforms = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406],
                         std=[0.229, 0.224, 0.225])
])


def main(args):
    train_writer = SummaryWriter()
    validation_writer = SummaryWriter()
    word_dict = json.load(open(args.data + '/word_dict.json', 'r'))
    vocabulary_size = len(word_dict)

    encoder = Encoder()
    decoder = Decoder(vocabulary_size)

    encoder.cuda()
    decoder.cuda()

    optimizer = optim.Adam(decoder.parameters(), lr=args.lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, args.step_size)
    cross_entropy_loss = nn.CrossEntropyLoss().cuda()

    train_loader = torch.utils.data.DataLoader(
        ImageCaptionDataset(data_transforms, args.data),
        batch_size=args.batch_size, shuffle=True, num_workers=1)

    val_loader = torch.utils.data.DataLoader(
        ImageCaptionDataset(data_transforms, args.data, split_type='val'),
        batch_size=args.batch_size, shuffle=True, num_workers=1)

    print('Starting training with {}'.format(args))
    for epoch in range(1, args.epochs + 1):
        scheduler.step()
        train(epoch, encoder, decoder, optimizer, cross_entropy_loss,
              train_loader, args.alpha_c, args.log_interval, train_writer)
        validate(epoch, encoder, decoder, cross_entropy_loss, val_loader,
                 args.alpha_c, args.log_interval, validation_writer)
        model_file = 'model/model_' + str(epoch) + '.pth'
        torch.save(decoder.state_dict(), model_file)
        print('Saved model to ' + model_file)
    train_writer.close()
    validation_writer.close()


def train(epoch, encoder, decoder, optimizer, cross_entropy_loss, data_loader, alpha_c, log_interval, writer):
    encoder.eval()
    decoder.train()

    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()
    for batch_idx, (imgs, captions) in enumerate(data_loader):
        imgs, captions = Variable(imgs).cuda(), Variable(captions).cuda()
        img_features = encoder(imgs)
        optimizer.zero_grad()
        preds, alphas = decoder(img_features, captions)
        targets = captions[:, 1:]

        targets = pack_padded_sequence(targets, [len(tar) - 1 for tar in targets], batch_first=True)[0]
        preds = pack_padded_sequence(preds, [len(pred) - 1 for pred in preds], batch_first=True)[0]

        att_regularization = alpha_c * ((1 - alphas.sum(1))**2).mean()

        loss = cross_entropy_loss(preds, targets)
        loss += att_regularization
        loss.backward()
        optimizer.step()

        total_caption_length = sum([len(caption) for caption in captions])
        acc1, acc5 = accuracy(preds, targets, topk=(1, 5))
        losses.update(loss.item(), total_caption_length)
        top1.update(acc1[0], total_caption_length)
        top5.update(acc5[0], total_caption_length)

        writer.add_scalar('train/epoch_{}_loss'.format(epoch), loss.item(), batch_idx)
        writer.add_scalar('train/epoch_{}_top1_acc'.format(epoch), acc1[0], batch_idx)
        writer.add_scalar('train/epoch_{}_top5_acc'.format(epoch), acc5[0], batch_idx)
        if batch_idx % log_interval == 0:
            print('Train Batch: [{0}/{1}]\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Top 1 Accuracy {top1.val:.3f} ({top1.avg:.3f})\t'
                  'Top 5 Accuracy {top5.val:.3f} ({top5.avg:.3f})'.format(
                      batch_idx, len(data_loader), loss=losses, top1=top1, top5=top5))


def validate(epoch, encoder, decoder, cross_entropy_loss, data_loader, alpha_c, log_interval, writer):
    encoder.eval()
    decoder.eval()

    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()
    with torch.no_grad():
        for batch_idx, (imgs, captions) in enumerate(data_loader):
            imgs, captions = Variable(imgs).cuda(), Variable(captions).cuda()
            img_features = encoder(imgs)
            preds, alphas = decoder(img_features, captions)
            targets = captions[:, 1:]

            targets = pack_padded_sequence(targets, [len(tar) - 1 for tar in targets], batch_first=True)[0]
            preds = pack_padded_sequence(preds, [len(pred) - 1 for pred in preds], batch_first=True)[0]

            att_regularization = alpha_c * ((1 - alphas.sum(1))**2).mean()

            loss = cross_entropy_loss(preds, targets)
            loss += att_regularization

            total_caption_length = sum([len(caption) for caption in captions])
            acc1, acc5 = accuracy(preds, targets, topk=(1, 5))
            losses.update(loss.item(), total_caption_length)
            top1.update(acc1[0], total_caption_length)
            top5.update(acc5[0], total_caption_length)

            writer.add_scalar('val/epoch_{}_loss'.format(epoch), loss.item(), batch_idx)
            writer.add_scalar('val/epoch_{}_top1_acc'.format(epoch), acc1[0], batch_idx)
            writer.add_scalar('val/epoch_{}_top5_acc'.format(epoch), acc5[0], batch_idx)
            if batch_idx % log_interval == 0:
                print('Validation Batch: [{0}/{1}]\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Top 1 Accuracy {top1.val:.3f} ({top1.avg:.3f})\t'
                      'Top 5 Accuracy {top5.val:.3f} ({top5.avg:.3f})'.format(
                          batch_idx, len(data_loader), loss=losses, top1=top1, top5=top5))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Show, Attend and Tell')
    parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                        help='batch size for training (default: 64)')
    parser.add_argument('--epochs', type=int, default=10, metavar='E',
                        help='number of epochs to train for (default: 10)')
    parser.add_argument('--lr', type=float, default=1e-3, metavar='LR',
                        help='learning rate of the decoder (default: 1e-3)')
    parser.add_argument('--step-size', type=int, default=5,
                        help='step size for learning rate annealing (default: 5)')
    parser.add_argument('--alpha-c', type=float, default=1, metavar='A',
                        help='regularization constant (default: 1)')
    parser.add_argument('--log-interval', type=int, default=100, metavar='L',
                        help='number of batches to wait before logging training stats (default: 100)')
    parser.add_argument('--data', type=str, default='data/coco',
                        help='path to data images (default: data/coco)')

    main(parser.parse_args())
