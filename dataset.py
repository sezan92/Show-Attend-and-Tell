import json, os
import torch
from collections import Counter
from PIL import Image
from torch.utils.data import Dataset


def pil_loader(path):
    with open(path, 'rb') as f:
        img = Image.open(f)
        return img.convert('RGB')


class ImageCaptionDataset(Dataset):
    def __init__(self, transform, split_type='train'):
        super(ImageCaptionDataset, self).__init__()
        self.transform = transform

        self.word_count = Counter()
        self.caption_img_idx = {}
        self.img_paths = json.load(open('{}_img_paths.json'.format(split_type), 'r'))
        self.captions = json.load(open('{}_captions.json'.format(split_type), 'r'))

    def __getitem__(self, index):
        img_path = self.img_paths[index]
        img = pil_loader(img_path)
        if self.transform is not None:
            img = self.transform(img)

        return torch.FloatTensor(img), torch.tensor(self.captions[index])

    def __len__(self):
        return len(self.captions)
