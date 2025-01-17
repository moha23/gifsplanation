import matplotlib.pyplot as plt
import torch
from torch.nn import functional as F
import glob
import numpy as np
import skimage, skimage.filters
import sklearn, sklearn.metrics
import captum, captum.attr
import torch, torch.nn
import pickle
from PIL import ImageDraw
import pandas as pd
import shutil
import os,sys
import torchxrayvision as xrv
from torchvision import transforms

def compute_attribution(image, method, clf, label, plot=False, ret_params=False, fixrange=None, p=0.0, ae=None, sigma=0, threshold=False):
    print('=============================Inside Compute Attribution===============================================')
    image = image.clone().detach()
    image_shape = image.shape[-2:]
    def clean(saliency):
        saliency = np.abs(saliency)
        if sigma > 0:
            saliency = skimage.filters.gaussian(saliency, 
                        mode='constant', 
                        sigma=(sigma, sigma), 
                        truncate=3.5)
        if threshold != False:
            saliency = thresholdf(saliency, 95 if threshold == True else threshold)
        return saliency
    
    if "latentshift" in method:
        z = ae.encode(image).detach()
        z.requires_grad = True
        xp = ae.decode(z, image_shape)
        # bring to 0,1 here
        xp = (xp+1)/2
        # pred_logits = F.softmax(clf((image*p + xp*(1-p))))
        pred_logits = F.softmax(clf(((torch.nn.Upsample([224,224])(image))*p + (torch.nn.Upsample([224,224])(xp))*(1-p))))
        pred_target = torch.argmax(pred_logits, dim=1)
        print('Ground Truth:', int(label))
        print('Initial pred_logits:', pred_logits)
        print('Initial pred_target:', pred_target)
        if pred_target==label:
          target = clf.pathologies[int(label.item())]
          print('pred_target == label, hence same target chosen:',target)
          if target == 'Normal':
              parampath = 'corrClf-Normal'
          else:
              parampath = 'corrClf-Glaucoma'
        else:
          target = clf.pathologies[pred_target.item()]
          print('pred_target != label, hence target same as pred_target:',target)
          if target == 'Normal':
              parampath = 'incorrClf-Normal'
          else:
              parampath = 'incorrClf-Glaucoma'
        pred = pred_logits[:,clf.pathologies.index(target)]
        print('Initial pred1:', pred)
        # pred = F.sigmoid(clf((image*p + xp*(1-p))))[:,clf.pathologies.index(target)]
        dzdxp = torch.autograd.grad((pred), z)[0]
        
        cache = {}
        def compute_shift(lam):
            #print(lam)
            if lam not in cache:
                xpp = ae.decode(z+dzdxp*lam, image_shape).detach()
                # bring to 0,1 here    
                xpp = (xpp+1)/2
                # pred1 = F.softmax(clf((image*p + xpp*(1-p))))[:,clf.pathologies.index(target)].detach().cpu().numpy()
                imageu = torch.nn.Upsample([224,224])(image)
                xppu = torch.nn.Upsample([224,224])(xpp)
                pred1 = F.softmax(clf((imageu*p + xppu*(1-p))))[:,clf.pathologies.index(target)].detach().cpu().numpy()
                cache[lam] = xpp, pred1
            return cache[lam]
        
        #determine range
        #initial_pred = pred.detach().cpu().numpy()
        _, initial_pred = compute_shift(0)
        print('Initial pred2:', initial_pred)
        
        if fixrange:
            lbound,rbound = fixrange
        else:
            #search params
            step = 10

            #left range
            lbound = 0
            last_pred = initial_pred
            while True:
                xpp, cur_pred = compute_shift(lbound)
        
                print("lbound",lbound, "last_pred",last_pred, "cur_pred",cur_pred)
                if last_pred < cur_pred:
                    print('BREAKING DUE TO last_pred < cur_pred')
                    break
                if initial_pred-0.5 > cur_pred:
                    print('BREAKING DUE TO  initial_pred-0.5 > cur_pred')
                    break
                if lbound <= -1000:
                    print('BREAKING DUE TO  lbound <= -1000')
                    break
                last_pred = cur_pred
                if np.abs(lbound) < step:
                    lbound = lbound - 1
                else:
                    lbound = lbound - step

            #right range
            rbound = 0
#             last_pred = initial_pred
#             while True:
#                 xpp, cur_pred = compute_shift(rbound)
#                 #print("rbound",rbound, "last_pred",last_pred, "cur_pred",cur_pred)
#                 if last_pred > cur_pred:
#                     break
#                 if initial_pred+0.05 < cur_pred:
#                     break
#                 if rbound >= 1000:
#                     break
#                 last_pred = cur_pred
#                 if np.abs(rbound) < step:
#                     rbound = rbound + 1
#                 else:
#                     rbound = rbound + step
        
        print('initial_pred:',initial_pred,'final lbound:',lbound,'final rbound:',rbound)
        #lambdas = np.arange(lbound,rbound,(rbound+np.abs(lbound))//10)
        lambdas = np.arange(lbound,rbound,np.abs((lbound-rbound)/10))
        print('learnt lambdas:', lambdas)
        ###########################
        
        y = []
        dimgs = []
        xp = ae.decode(z,image_shape)   
        xp = (xp+1)/2
        xp = xp[0][0].unsqueeze(0).unsqueeze(0).detach()
        # bring to 0,1 here
        print('For each lambda, acquiring new preds and counterfactuals....')
        for lam in lambdas:
            
            xpp, pred = compute_shift(lam)
            dimgs.append(xpp.cpu().numpy())
            y.append(pred)
            
        if ret_params:
            params = {}
            params["dimgs"] = dimgs
            params["lambdas"] = lambdas
            params["y"] = y
            params["initial_pred"] = initial_pred
            params["target"] = target
            params["path"] = parampath
            print('=============================End Compute Attribution, returning params===============================================')
            return params
        
        if plot:
            
            px = 1/plt.rcParams['figure.dpi']
            full_frame(image[0][0].shape[0]*px,image[0][0].shape[1]*px)
            plt.imshow(image.detach().cpu()[0][0], interpolation='none', cmap="gray")
            plt.title("image")
            plt.show()
            px = 1/plt.rcParams['figure.dpi']
            full_frame(xp[0][0].shape[0]*px,xp[0][0].shape[1]*px)
            plt.imshow(xp.detach().cpu()[0][0], interpolation='none', cmap="gray")
            plt.title("image_recon")
            plt.show()
            
            plt.plot(lambdas,y)
            plt.xlabel("lambda shift");
            plt.ylabel("Prediction of " + target);
            plt.show()
        
        if "-max" in method:
            dimage = np.max(np.abs(xp.cpu().numpy()[0][0] - dimgs[0][0]),0)
        elif "-mean" in method:
            dimage = np.mean(np.abs(xp.cpu().numpy()[0][0] - dimgs[0][0]),0)
        elif "-mm" in method:
            dimage = np.abs(dimgs[0][0][0] - dimgs[-1][0][0])
        elif "-int" in method:
            dimages = []
            for i in range(len(dimgs)-1):
                dimages.append(np.abs(dimgs[i][0][0] - dimgs[i+1][0][0]))
            dimage = np.mean(dimages,0)
        else:
            raise Exception("Unknown mode")
        
        dimage = clean(dimage)
        return dimage
    
    if method == "grad":
        image.requires_grad = True
        pred = clf(image)[:,clf.pathologies.index(target)]
        dimage = torch.autograd.grad(torch.abs(pred), image)[0]
        dimage = dimage.detach().cpu().numpy()[0][0]
        dimage = clean(dimage)
        return dimage
    
    if method == "integrated":
        attr = captum.attr.IntegratedGradients(clf)
        dimage = attr.attribute(image, 
                                target=clf.pathologies.index(target),
                                n_steps=100, 
                                return_convergence_delta=False, 
                                internal_batch_size=1)
        dimage = dimage.detach().cpu().numpy()[0][0]
        dimage = clean(dimage)
        return dimage
    
    if method == "guided":
        
        attr = captum.attr.GuidedBackprop(clf)
        dimage = attr.attribute(image, target=clf.pathologies.index(target))
        dimage = dimage.detach().cpu().numpy()[0][0]
        dimage = clean(dimage)
        return dimage
    
    if method == "iterativedelete":
        
        lr = 1
        grads = []
        for i in range(20):
            image.requires_grad = True
            pred = clf(image)[:,clf.pathologies.index(target)]
            #print(pred)
            dimage = torch.autograd.grad(torch.abs(pred), image)[0]
            dimage = dimage.detach().cpu().numpy()[0][0]
            grads.append(dimage)
            
            dimage = thresholdf(dimage, 98)
            #print(image.shape, dimage.shape)
            image = image * torch.Tensor(dimage>0).cuda().unsqueeze(0).unsqueeze(0)
            image = image.clone().detach()
            
        dimage = np.mean(grads,0)
        dimage = clean(dimage)
        return dimage
    
def thresholdf(x, percentile):
    return x * (x > np.percentile(x, percentile))

def calc_iou(preds, gt_seg):
    gt_seg = gt_seg.astype(np.bool)
    seg_area_percent = (gt_seg > 0).sum()/(gt_seg != -1).sum() # percent of area
    preds = (thresholdf(preds, (1-seg_area_percent)*100) > 0).astype(np.bool)
    #EPS = 10e-16
    ret = {}
    ret["iou"] = (gt_seg & preds).sum() / ((gt_seg | preds).sum())
    ret["precision"] = sklearn.metrics.precision_score(gt_seg.flatten(),preds.flatten())
    ret["recall"] = sklearn.metrics.recall_score(gt_seg.flatten(),preds.flatten())  
    return ret


def run_eval(target, data, model, ae, to_eval=None, compute_recon=False, pthresh = 0, limit = 40,data_aug=None):
    dwhere = np.where(data.csv.has_masks & (data.labels[:,data.pathologies.index(target)]  == 1))[0]
    results = []
    
    if to_eval == None:
        to_eval = [
                   "latentshift-max", 
#                    "latentshift-mean", 
#                    "latentshift-mm", 
#                    "latentshift-int",
                   "grad", "integrated", "guided"
                    ]
    
    for method in to_eval:
        count = 0
        for idx in dwhere:
            #print(method, idx)
            imgresults = []
            
            if data_aug:
                # add for noise
                data.data_aug = data_aug
                
            sample = data[idx]

            if data.pathologies.index(target) not in sample["pathology_masks"]:
                #print("no mask found")
                continue
            image = torch.from_numpy(sample["img"]).unsqueeze(0).cuda()
            p = model(image)[:,model.pathologies.index(target)].detach().cpu().numpy()
            #print(p)
            if p > pthresh:
                dimage = compute_attribution(image, method, model, target, ae=ae)
                #print(method, dimage.shape)
                
                if data_aug:
                    #get version of masks that are clean
                    data.data_aug = None
                    sample = data[idx]  
                
                metrics = calc_iou(dimage, sample["pathology_masks"][data.pathologies.index(target)][0])
                if compute_recon:
                    recon = ae(image)["out"]
                    metrics["mse"] = float(((image-recon)**2).mean().detach().cpu().numpy())
                    metrics["mae"] = float(torch.abs(image-recon).mean().detach().cpu().numpy())
                metrics["idx"] = idx
                metrics["p"] = float(p)
                metrics["target"] = target
                metrics["method"] = method
                results.append(metrics)
                count += 1
                if count > limit:
                    break
    return pd.DataFrame(results)


def generate_video(
    params: dict,
    target_filename: str,
    watermark: bool = True,
    show_pred: bool = True,
    ffmpeg_path: str = "ffmpeg",
    temp_path: str = "/tmp/gifsplanation",
    show: bool = True,
    verbose: bool = True,
    extra_loops: int = 0,
    cmap: str = None,
):
    """Generate a video from the generated images.

    Args:
        params: The dict returned from the call to `attribute`.
        target_filename: The filename to write the video to. `.mp4` will
            be added to the end of the string.
        watermark: To add the probability output and the name of the
            method.
        ffmpeg_path: The path to call `ffmpeg`
        temp_path: A temp path to write images.
        show: To try and show the video in a jupyter notebook.
        verbose: True to print debug text
        extra_loops: The video does one loop by default. This will repeat
            those loops to make it easier to watch.
        cmap: The cmap value passed to matplotlib. e.g. 'gray' for a
            grayscale image.

    Returns:
        The filename of the video if show=False, otherwise it will
        return a video to show in a jupyter notebook.
    """

    if os.path.exists(target_filename + ".mp4"):
        os.remove(target_filename + ".mp4")

    shutil.rmtree(temp_path, ignore_errors=True)
    os.mkdir(temp_path)

    imgs = [h.transpose(1, 2, 0) for h in params["generated_images"]]

    # Add reversed so we have an animation cycle
    towrite = list(reversed(imgs)) + list(imgs)
    
    if show_pred:
        ys = list(reversed(params["preds"])) + list(params["preds"])

    for n in range(extra_loops):
        towrite += towrite
        if show_pred:
            ys += ys

    for idx, img in enumerate(towrite):
        path = f"{temp_path}/image-{idx}.png"
        write_frame(
            img, 
            path=path, 
            pred=ys[idx] if show_pred else None, 
            cmap=cmap, 
            watermark=watermark, 
            pred_max=max(ys) if show_pred else "",
        )

    # Command for ffmpeg to generate an mp4
    cmd = (
        f"{ffmpeg_path} -loglevel quiet -stats -y "
        f"-i {temp_path}/image-%d.png "
        f"-c:v libx264 -vf scale=-2:{imgs[0][0].shape[0]} "
        f"-profile:v baseline -level 3.0 -pix_fmt yuv420p "
        f"'{target_filename}.mp4'"
    )

    if verbose:
        print(cmd)
    output = subprocess.check_output(cmd, shell=True)
    if verbose:
        print(output)

    if show:
        # If we in a jupyter notebook then show the video.
        from IPython.core.display import Video

        try:
            return Video(
                target_filename + ".mp4",
                html_attributes="controls loop autoplay muted",
                embed=True,
            )
        except TypeError:
            return Video(target_filename + ".mp4", embed=True)
    else:
        return target_filename + ".mp4"


def full_frame(width=None, height=None):
    """Setup matplotlib so we can write to the entire canvas"""

    matplotlib.rcParams["savefig.pad_inches"] = 0
    figsize = None if width is None else (width, height)
    plt.figure(figsize=figsize)
    ax = plt.axes([0, 0, 1, 1], frameon=False)
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)
    plt.autoscale(tight=True)


def write_frame(img, path, text=None, pred=None, cmap=None, watermark=True, pred_max=1):

    px = 1 / plt.rcParams["figure.dpi"]
    full_frame(img.shape[0] * px, img.shape[1] * px)
    plt.imshow(img, interpolation="none", cmap=cmap)

    if pred:
        # Show pred as bar in upper left
        plt.text(
            0.05,
            0.95,
            f"{float(pred):1.2f} " + "█"*int(pred/pred_max*100),
            ha="left",
            va="top",
            transform=plt.gca().transAxes,
            size=img.shape[0]//120,
            backgroundcolor="white",
        )

    if text:
        # Write prob output in upper left
        plt.text(
            0.05,
            0.95,
            f"{float(text):1.1f}",
            ha="left",
            va="top",
            size=img.shape[0]//50,
            transform=plt.gca().transAxes,
        )

    if watermark:
        # Write method name in lower right
        plt.text(
            0.96,
            0.1,
            "gifsplanation",
            ha="right",
            va="bottom",
            size=img.shape[0]//30,
            transform=plt.gca().transAxes,
        )

    plt.savefig(
        path,
        bbox_inches="tight",
        pad_inches=0,
        transparent=False,
    )
    plt.close()
    
    
    
def generate_attributions(sample, model, target, ae, temp_path, dmerge, plot_iou=False, methods = ["image", "grad", "guided", "integrated", "latentshift-max"], threshold=True):

    image = torch.from_numpy(sample["img"]).unsqueeze(0).cuda()
    
    p = model(image)[:,model.pathologies.index(target)].detach().cpu()
    print(p)
    
    fig, ax = plt.subplots(1,len(methods), figsize=(8,3), dpi=350)
    for i, method in enumerate(methods):

        if method == "image":
            ax[i].imshow(image.detach().cpu()[0][0], interpolation='none', cmap="gray")
            #ax[i].set_ylabel(target + "\n" + str(model).replace("-DenseNet121",""), fontsize=7)
        else:
            
            if plot_iou and (threshold == True):
                gt_seg = sample["pathology_masks"][dmerge.pathologies.index(target)][0]
                seg_area_percent = (gt_seg > 0).sum()/(gt_seg != -1).sum() # percent of area
                threshold = (1-seg_area_percent)*100
            
            
            dimage = compute_attribution(image, method, model, target, ae=ae, threshold=threshold)

            ax[i].imshow(image.detach().cpu()[0][0], interpolation='none', cmap="gray")

            if plot_iou:
                iou = calc_iou(dimage, sample["pathology_masks"][dmerge.pathologies.index(target)][0])
                print(method,iou)
            
            dimage[dimage==0] = np.nan
            ax[i].imshow(dimage, interpolation='none', alpha=0.8, cmap="Reds");
            
            if plot_iou:
                ax[i].text(0, 0,"IoU:{:.3f}".format(iou["iou"]),
                     horizontalalignment='left',
                     verticalalignment='top', c="w", size=7)
                
            
        try:
            ax[i].imshow(sample["pathology_masks"][dmerge.pathologies.index(target)][0], interpolation='none', alpha=0.1);
        except:
            pass
        ax[i].get_xaxis().set_visible(False)
        ax[i].set_yticks([])
        #ax[i].get_yaxis().set_visible(False)
        ax[i].set_title(method, fontsize=8)
    fig.subplots_adjust(wspace=0, hspace=0);
    plt.show()
    
    
def test_epoch(model, dataset, target, limit=128, batch_size=128):

    labels = dataset.labels[:,dataset.pathologies.index(target)]
    num_to_sample = limit//len(np.unique(labels))
    np.random.seed(0)
    mask = np.hstack([np.random.choice(np.where(labels == l)[0], num_to_sample, replace=False) for l in np.unique(labels)])

    tlabels = labels[mask]
    
    dsub = xrv.datasets.SubsetDataset(dataset, mask)
    
    dl = torch.utils.data.DataLoader(dsub, batch_size=batch_size, num_workers=0, pin_memory=False)

    d_preds = []
    with torch.no_grad():
        for i, batch in enumerate(dl):
            imgs = batch["img"].cuda()
            pred = model(imgs)
            d_preds.append(pred.detach().cpu().numpy())
            if i %10 == 0:
                print(i)
    d_preds = np.concatenate(d_preds)
    tpred = d_preds[:,model.pathologies.index(target)]
    
    task_auc = sklearn.metrics.roc_auc_score(tlabels, tpred)
    return task_auc
