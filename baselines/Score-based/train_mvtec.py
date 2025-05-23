import mvtec
from mvtec import MVTecDataset

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.optim import Adam, AdamW
from torch.utils.data import DataLoader

from sklearn.metrics import roc_auc_score, auc
from sklearn.metrics import roc_curve

import numpy as np
import pandas as pd
import functools
import os
import random
import argparse
import warnings
import gc
from unet import UNet
from torch_ema import ExponentialMovingAverage

warnings.filterwarnings("ignore", category=UserWarning)

def parse_args():
    parser = argparse.ArgumentParser('configuration')
    parser.add_argument('--dataset_path', type=str, default='./mvtec/')
    parser.add_argument('--save_path', type=str, default='./final_save/')
    parser.add_argument('--n_epochs', type=int, default=1)
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--batch_size', type=int, default=16)
    parser.add_argument('--num_workers', type=int, default=4)
    parser.add_argument('--class_name', type=str, default='all')
    return parser.parse_args()

def setup_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

def marginal_prob_std(t, sigma, device):
    t = torch.tensor(t, device=device)
    return torch.sqrt((sigma**(2 * t) - 1.) / 2. / np.log(sigma))

def diffusion_coeff(t, sigma, device):
    return torch.tensor(sigma**t, device=device)

def loss_fn(model, x, marginal_prob_std, eps=1e-5):
    random_t = torch.rand(x.shape[0], device=x.device) * (1. - eps) + eps  
    z = torch.randn_like(x)
    std = marginal_prob_std(random_t)
    perturbed_x = x + z * std[:, None, None, None]
    score = model(perturbed_x, random_t)
    loss = torch.mean(torch.sum((score * std[:, None, None, None] + z)**2, dim=(1,2,3)))
    return loss
    
def roc_auc_pxl(gt, score):
    pixel_auroc = roc_auc_score(gt.flatten(), score.flatten())
    return pixel_auroc

def cal_pxl_roc(gt_mask, scores):
    fpr, tpr, _ = roc_curve(gt_mask.flatten(), scores.flatten())
    pixel_auroc = roc_auc_pxl(gt_mask.flatten(), scores.flatten())
    return fpr, tpr, pixel_auroc

def roc_auc_img(gt, score):
    img_auroc = roc_auc_score(gt, score)
    return img_auroc

def cal_img_roc(scores, gt_list):
    img_scores = scores.reshape(scores.shape[0], -1).max(axis=1)
    gt_list = np.asarray(gt_list)
    fpr, tpr, _ = roc_curve(gt_list, img_scores)
    img_auroc = roc_auc_img(gt_list, img_scores)
    return fpr, tpr, img_auroc

def run():
    args = parse_args()
    
    device = torch.device("cuda:0" if torch.cuda.is_available() else 'cpu')
    print(device)
    print(torch.version.cuda)

    # class_names = mvtec.CLASS_NAMES if args.class_name == 'all' else [args.class_name]
    # class_name = 'level_0_train'
    class_names = ['bottle/train/good', 'cable/train/good', 'capsule/train/good', 'carpet/train/good', 'grid/train/good', 'hazelnut/train/good', 'leather/train/good', 'metal_nut/train/good', 'pill/train/good', 'screw/train/good', 'tile/train/good', 'transistor/train/good', 'wood/train/good', 'zipper/train/good']
    for class_name in class_names:
        train_dataset  = MVTecDataset(dataset_path  = args.dataset_path, 
                                        class_name    =  class_name, 
                                        is_train      =  True)

        train_loader   = DataLoader(dataset         = train_dataset, 
                                    batch_size      = args.batch_size, 
                                    pin_memory      = True,
                                    shuffle         = True,
                                    drop_last       = False,
                                    num_workers     =  args.num_workers)
        
        test_dataset   = MVTecDataset(dataset_path  = args.dataset_path, 
                                        class_name    =  class_name, 
                                        is_train      =  False)

        test_loader    = DataLoader(dataset         =   test_dataset, 
                                    batch_size      =   args.batch_size, 
                                    pin_memory      =   True,
                                    shuffle         =   False,
                                    drop_last       =   False,
                                    num_workers     =   args.num_workers)
        
        marginal_prob_std_fn = functools.partial(marginal_prob_std, sigma = 25, device = device)
        diffusion_coeff_fn = functools.partial(diffusion_coeff, sigma = 25, device = device)
        
        score_model = UNet(marginal_prob_std = marginal_prob_std_fn,
                            n_channels        = 3,
                            n_classes         = 3,
                            embed_dim         = 256)
        
        score_model = score_model.to(device)
        
        optimizer = AdamW(score_model.parameters(), lr=args.lr, weight_decay=0.001)
        scheduler = optim.lr_scheduler.MultiStepLR(optimizer, milestones=[1000,2000], gamma=0.1, verbose = False)
        ema = ExponentialMovingAverage(score_model.parameters(), decay=0.9999)
        
        for epoch in range(1,args.n_epochs+1):
            total_loss = 0.
            num_items = 0
            score_model.train()
            for x, _, _ in train_loader:
                # import pdb; pdb.set_trace()
                x = x.to(device)    
                loss = loss_fn(score_model, x, marginal_prob_std_fn)
                optimizer.zero_grad()
                loss.backward()    
                optimizer.step()
                ema.update()
                total_loss += loss.item() * x.shape[0]
                num_items += x.shape[0]
            scheduler.step()
            
            avg_loss = total_loss / num_items
                
            print('Class : {} [{}/{}] -> Average Loss: {:.2f}'.format(class_name, epoch, args.n_epochs, avg_loss))
            
            score_model.eval()
            if (epoch) % args.n_epochs == 0:
                with ema.average_parameters():
                    all_scores = None
                    all_mask = None
                    all_x = None
                    all_y = None
                    num_iter = 3
                    perturbed_t = 1e-3

                    for x, y, mask in test_loader:
                        x = x.to(device)
                        sample_batch_size = x.shape[0]
                        t = torch.ones(sample_batch_size, device=device) * perturbed_t

                        scores = 0.
                        with torch.no_grad():
                            for i in range(num_iter):
                                ms = marginal_prob_std_fn(t)[:, None, None, None]
                                g = diffusion_coeff_fn(t)[:, None, None, None]
                                n = torch.randn_like(x)*ms
                                z = x + n
                                score = score_model(z, t)
                                score = score*ms**2 + n
                                scores += (score**2).mean(1, keepdim = True)
                        scores /= num_iter

                        all_scores = torch.cat((all_scores, scores), dim = 0) if all_scores != None else scores
                        all_mask = torch.cat((all_mask,mask), dim = 0) if all_mask != None else mask
                        all_x = torch.cat((all_x,x), dim = 0) if all_x != None else x
                        all_y = torch.cat((all_y,y), dim = 0) if all_y != None else y

                    # import pdb; pdb.set_trace()
                    heatmaps = all_scores.cpu().detach().sum(1, keepdim = True)
                    heatmaps = F.interpolate(torch.Tensor(heatmaps), (256, 256), mode = "bilinear", align_corners=False)
                    heatmaps = F.avg_pool2d(heatmaps, 31,1, padding = 15).numpy()
                    # sum, max: np.sum(heatmaps[0]), np.max(heatmaps[0])
                    # sums = []
                    # maxs = []
                    # for i in range(heatmaps.shape[0]):
                    #     sample = heatmaps[i]
                        
                    #     sample_sum = np.sum(sample)
                    #     sample_max = np.max(sample)
                        
                    #     sums.append(sample_sum)
                    #     maxs.append(sample_max)

                    # # Create a DataFrame with the sums and maxs
                    # df = pd.DataFrame({
                    #     'sum': sums,
                    #     'max': maxs
                    # })
                    # # Save the DataFrame to a CSV file
                    # df.to_csv(f'./outputs/evaluate_{class_name}_heatmaps_results.csv', index=False)
                    # _, _, img_auroc = cal_img_roc(heatmaps.max(axis = (1,2,3)), all_y)
                    # _, _, pixel_auroc = cal_pxl_roc(all_mask, heatmaps)

                    model_save_path = os.path.join(args.save_path, "models")
                    result_save_path = os.path.join(args.save_path, "results")

                    if not os.path.exists(model_save_path):
                        os.makedirs(model_save_path)
                    if not os.path.exists(result_save_path):
                        os.makedirs(result_save_path)

                    # torch.save(score_model.state_dict(), os.path.join(model_save_path, class_name + ".pth"))
                    torch.save(score_model.state_dict(), os.path.join(model_save_path, class_name.split('/')[0] + '_visa' + ".pth"))

if __name__ == '__main__':
    setup_seed(7777)
    run()
