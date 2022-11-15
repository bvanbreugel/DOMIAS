from __future__ import absolute_import
from __future__ import print_function
from __future__ import division
import argparse
import torch
# from scipy.stats import norm
parser = argparse.ArgumentParser()

parser.add_argument('--gan_method', type=str, default='TVAE', choices=["adsgan-tf", "TVAE", "CTGAN", "KDE", 'gaussian_copula',
                                                                            'adsgan',
                                                                            'tvae',
                                                                            'privbayes',
                                                                            'marginal_distributions',
                                                                            'bayesian_network',
                                                                            'ctgan',
                                                                            'copulagan',
                                                                            'nflow',
                                                                            'rtvae',
                                                                            'pategan'], help='benchmarking generative model used for synthesis')
parser.add_argument('--epsilon_adsgan', type=float, default=0.0, help='hyper-parameter in ads-gan')
parser.add_argument('--density_estimator', type=str, default="prior", choices=["bnaf", "kde", "prior"])
parser.add_argument('--training_size_list', nargs='+', type=int, default=[100], help='size of training dataset')
parser.add_argument('--held_out_size_list', nargs='+', type=int, default=[10000], help='size of held-out dataset')
parser.add_argument('--training_epoch_list', nargs='+', type=int, default=[2000], help='# training epochs')
parser.add_argument('--gen_size_list', nargs='+', type=int, default=[10000], help='size of generated dataset')
parser.add_argument('--seed', type=int, default=0)
parser.add_argument("--gpu_idx", default=3, type=int)
parser.add_argument("--device", type=str, default=None)
parser.add_argument(
    "--dataset",
    type=str,
    default="housing",
    choices=["MAGGIC", "housing", "synthetic", "Digits", "Covtype", "SynthGaussian"],
)
parser.add_argument("--learning_rate", type=float, default=1e-2)
parser.add_argument("--batch_dim", type=int, default=50)
parser.add_argument("--clip_norm", type=float, default=0.1)
parser.add_argument("--epochs", type=int, default=50)
parser.add_argument("--patience", type=int, default=20)
parser.add_argument("--cooldown", type=int, default=10)
parser.add_argument("--early_stopping", type=int, default=100)
parser.add_argument("--decay", type=float, default=0.5)
parser.add_argument("--min_lr", type=float, default=5e-4)
parser.add_argument("--polyak", type=float, default=0.998)
parser.add_argument("--flows", type=int, default=5)
parser.add_argument("--layers", type=int, default=3)
parser.add_argument("--hidden_dim", type=int, default=32)
parser.add_argument(
    "--residual", type=str, default="gated", choices=[None, "normal", "gated"]
)
parser.add_argument("--expname", type=str, default="")
parser.add_argument("--load", type=str, default=None)
parser.add_argument("--save", action="store_true")
parser.add_argument("--tensorboard", type=str, default="tensorboard")
parser.add_argument("--shifted_column", type = int, default = None)
parser.add_argument("--zero_quantile", type = float, default = 0.3)
parser.add_argument("--reference_kept_p", type = float, default = 1.0)

args = parser.parse_args()
args.device = f"cuda:{args.gpu_idx}"

alias = f'gp_shift{args.shifted_column}_zq{args.zero_quantile}_kp{args.reference_kept_p}_{args.batch_dim}_{args.hidden_dim}_{args.layers}_{args.epochs}_{args.gan_method}_{args.epsilon_adsgan}_{args.density_estimator}_{args.dataset}_trn_sz{args.training_size_list}_ref_sz{args.held_out_size_list}_gen_sz{args.gen_size_list}_{args.seed}'

if args.gpu_idx is not None:
    torch.cuda.set_device(args.gpu_idx)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

from bnaf.bnaf_den_est import *
from baselines_stable import *
from bnaf.datasets import *
import numpy as np
import pandas as pd
from ctgan import CTGANSynthesizer
from ctgan import load_demo
import ctgan
from sklearn.model_selection import train_test_split
from sdv.tabular import TVAE
from sdv.evaluation import evaluate
from scipy import stats
from sklearn import metrics
from sklearn.metrics import accuracy_score
from metrics.combined import compute_metrics
import os
from adsgan import adsgan
from metrics.feature_distribution import feature_distribution
from metrics.compute_wd import compute_wd
from metrics.compute_identifiability import compute_identifiability

if args.gan_method not in ["TVAE", "KDE", "CTGAN"]:
    from synthcity.plugins import Plugins
os.makedirs('results_folder', exist_ok=True)


# %% Import necessary functions
# from data_loader import load_adult_data

# %% Experiment main function
def compute_bw(X, X2=None, num_runs=10):
    p_t = stats.gaussian_kde(X.transpose(1,0), bw_method = 'silverman')
    bw_max = p_t.scotts_factor()
    bws = np.logspace(np.log(bw_max/3), np.log(bw_max*1), num_runs, base=np.exp(1))
    scores = np.zeros(num_runs)
    for i, bw in enumerate(bws):
        if X2 is None:
            X, X2 = train_test_split(X, test_size=0.1)
        p_t = stats.gaussian_kde(X.transpose(1,0),bw_method = bw)
        scores[i] = np.mean(np.log(1000*p_t(X2.transpose(1,0))))
        print('bw', i, ':', bw, ' - score:', scores[i])
    
    return bws[np.argmax(scores)]

def exp_main(args, orig_data_frame):

    orig_data = orig_data_frame
    # Generate synthetic data
    params = dict()
    params["lamda"] = args.lamda
    params["iterations"] = args.iterations
    params["h_dim"] = args.h_dim
    params["z_dim"] = args.z_dim
    params["mb_size"] = args.mb_size

    synth_data_list = adsgan(orig_data, params)
    synth_data = synth_data_list[0]
    print("Finish synthetic data generation")

    # Performance measures
    # (1) Feature distributions
    feat_dist = feature_distribution(orig_data, synth_data)
    print("Finish computing feature distributions")

    # (2) Wasserstein Distance (WD)
    print("Start computing Wasserstein Distance")
    wd_measure = compute_wd(orig_data, synth_data, params)
    print("WD measure: " + str(wd_measure))

    # (3) Identifiability
    identifiability = compute_identifiability(orig_data, synth_data)
    print("Identifiability measure: " + str(identifiability))

    return orig_data, synth_data_list, [feat_dist, wd_measure, identifiability]


performance_logger = {}

''' 1. load dataset'''
if args.dataset == "MAGGIC":
    dataset = MAGGIC('')
    dataset = np.vstack((dataset.train.x, dataset.val.x, dataset.test.x))
    np.random.seed(1)
    np.random.shuffle(dataset)
    print('dataset size,', dataset.shape)
    ndata = dataset.shape[0]
elif args.dataset == "housing":
    from sklearn.datasets import fetch_california_housing
    from sklearn.preprocessing import StandardScaler
    def data_loader():
        # np.random.multivariate_normal([0],[[1]], n1)*std1 # non-training data
        scaler = StandardScaler()
        X = fetch_california_housing().data
        np.random.shuffle(X)
        return scaler.fit_transform(X)
    dataset = data_loader()
    print('dataset size,', dataset.shape)
    ndata = dataset.shape[0]
elif args.dataset == "synthetic":
    dataset = np.load(f'../dataset/synthetic_gaussian_{20}_{10}_{30000}_train.npy')
    print('dataset size,', dataset.shape)
    ndata = dataset.shape[0]
elif args.dataset == 'Digits':
    from sklearn.datasets import load_digits
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    dataset = load_digits().data
    dataset = scaler.fit_transform(dataset)
    np.random.seed(1)
    np.random.shuffle(dataset)
    #X, y = dataset['data'], dataset['target']
    print('dataset size,', dataset.shape)
    ndata = dataset.shape[0]
elif args.dataset == 'Covtype':
    from sklearn.datasets import fetch_covtype
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    dataset = fetch_covtype().data
    dataset = scaler.fit_transform(dataset)
    np.random.seed(1)
    np.random.shuffle(dataset)
    #X, y = dataset['data'], dataset['target']-1
    print('dataset size,', dataset.shape)
    ndata = dataset.shape[0]
elif args.dataset == 'SynthGaussian':
    dataset = np.random.randn(200000,3)
    ndata = dataset.shape[0]
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import multivariate_normal

class gaussian():
    def __init__(self, X):
        var = np.std(X, axis=0)**2
        mean = np.mean(X, axis=0)
        self.rv = multivariate_normal(mean, np.diag(var))

    def pdf(self, Z):
        return self.rv.pdf(Z)        
class normal_func():
    def __init__(self, X):
        self.var = np.std(X, axis=0)**2
        self.mean = np.mean(X, axis=0)
        print('mean , var', self.mean, self.var)
        #self.rv = multivariate_normal(mean, np.diag(var))

    def pdf(self, Z):
        #return self.rv.pdf(Z)   
        return multivariate_normal.pdf(Z, self.mean, np.diag(self.var))
#         return multivariate_normal.pdf(Z, np.zeros_like(self.mean), np.diag(np.ones_like(self.var)))

class normal_func_feat():
    def __init__(self, X, continuous = [1,1,1,1,1,1,0,0]):
        if continuous == 'all':
            self.feat = np.ones(X.shape[1]).astype(bool)
        else:
            if np.any(np.array(continuous)>1) or len(continuous) != X.shape[1]:
                raise ValueError('Continous variable needs to be boolean')
            self.feat = np.array(continuous).astype(bool)
        
        if np.sum(self.feat)==0:
            raise ValueError('there needs to be at least one continuous feature')
            
        for i in np.arange(X.shape[1])[self.feat]:
            if len(np.unique(X[:,i]))<10:
                print(f'Warning: feature {i} does not seem continous. CHECK')
            
        self.var = np.std(X[:,self.feat], axis=0)**2
        self.mean = np.mean(X[:,self.feat], axis=0)
        #self.rv = multivariate_normal(mean, np.diag(var))

    def pdf(self, Z):
        return multivariate_normal.pdf(Z[:,self.feat], self.mean, np.diag(self.var))        

norm = normal_func_feat(dataset)

''' 2. training-test-addition split'''
for SIZE_PARAM in args.training_size_list:
    for ADDITION_SIZE in args.held_out_size_list:
        for TRAINING_EPOCH in args.training_epoch_list:
            if SIZE_PARAM*2 + ADDITION_SIZE >= ndata:
                continue
            '''
            Process the dataset for covariant shift experiments
            '''
            if args.shifted_column is not None:
                zero_quantile = args.zero_quantile
                shifted_column = args.shifted_column
                reference_kept_p = args.reference_kept_p
                thres = np.quantile(dataset[:,shifted_column], zero_quantile) + 0.01
                dataset[:,shifted_column][dataset[:,shifted_column] < thres] = -999.
                dataset[:,shifted_column][dataset[:,shifted_column] > thres] = 999.
                dataset[:,shifted_column][dataset[:,shifted_column] == -999.] = 0.
                dataset[:,shifted_column][dataset[:,shifted_column] == 999.] = 1.

                training_set = dataset[:SIZE_PARAM]
                print('training data (D_mem) without A=0',training_set[training_set[:,shifted_column] == 1].shape)
                training_set = training_set[training_set[:,shifted_column] == 1]

                test_set = dataset[SIZE_PARAM:2*SIZE_PARAM]
                test_set = test_set[:len(training_set)]
                addition_set = dataset[-ADDITION_SIZE:]
                addition_set2 = dataset[-2*ADDITION_SIZE:-ADDITION_SIZE]

                
                #test_set_A1 = test_set[test_set[:, shifted_column] == 1]
                #test_set_A0 = test_set[test_set[:, shifted_column] == 0]
                #test_set_A0_kept = test_set_A0[:int(len(test_set_A0)*reference_kept_p)]
                addition_set_A1 = addition_set[addition_set[:, shifted_column] == 1]
                addition_set_A0 = addition_set[addition_set[:, shifted_column] == 0]
                addition_set2_A1 = addition_set2[addition_set2[:, shifted_column] == 1]
                addition_set2_A0 = addition_set2[addition_set2[:, shifted_column] == 0]
                addition_set_A0_kept = addition_set_A0[:int(len(addition_set_A0)*reference_kept_p)]
                addition_set2_A0_kept = addition_set2_A0[:int(len(addition_set2_A0)*reference_kept_p)]
                if reference_kept_p > 0:
                    addition_set = np.concatenate((addition_set_A1, addition_set_A0_kept), 0)
                    addition_set2 = np.concatenate((addition_set2_A1, addition_set2_A0_kept), 0)
                    #test_set = np.concatenate((test_set_A1, test_set_A0_kept), 0)
                else:
                    addition_set = addition_set_A1
                    addition_set2 = addition_set2_A1
                    #test_set = test_set_A1
                    
                #test_set = test_set[:min(len(training_set), len(test_set))]
                #training_set = training_set[:min(len(training_set), len(test_set))]
                
                SIZE_PARAM = len(training_set)
                ADDITION_SIZE = len(addition_set)

                # hide column A
                training_set = np.delete(training_set, shifted_column, 1)
                test_set = np.delete(test_set, shifted_column, 1)
                addition_set = np.delete(addition_set, shifted_column, 1)
                addition_set2 = np.delete(addition_set2, shifted_column, 1)
                dataset = np.delete(dataset, shifted_column, 1) 
            else:
                training_set = dataset[:SIZE_PARAM]
                test_set = dataset[SIZE_PARAM:2*SIZE_PARAM]
                addition_set = dataset[-ADDITION_SIZE:]
                addition_set2 = dataset[-2*ADDITION_SIZE:-ADDITION_SIZE]
            performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'] = {}
            ''' 3. Synthesis with TVAE'''
            df = pd.DataFrame(training_set)
            df.columns = [str(_) for _ in range(dataset.shape[1])]
            if args.gan_method == 'TVAE':
                syn_model = TVAE(epochs=TRAINING_EPOCH)
                syn_model.fit(df)
            elif args.gan_method == 'CTGAN':
                syn_model = CTGANSynthesizer(epochs=TRAINING_EPOCH)
                syn_model.fit(df)
            elif args.gan_method == "KDE":
                kde_model = stats.gaussian_kde(training_set.transpose(1, 0))
            elif args.gan_method == "adsgan-tf":
                pass
            else:  # synthcity
                syn_model = Plugins().get(args.gan_method)
                if args.gan_method == 'adsgan':
                    syn_model.lambda_identifiability_penalty = args.epsilon_adsgan
                    syn_model.seed = args.gpu_idx
                elif args.gan_method == 'pategan':
                    syn_model.dp_delta = 1e-5
                    syn_model.dp_epsilon = args.epsilon_adsgan
                syn_model.fit(df)

            for N_DATA_GEN in args.gen_size_list:
                if args.gan_method == 'KDE':
                    samples = pd.DataFrame(kde_model.resample(N_DATA_GEN).transpose(1, 0))
                    samples_val = pd.DataFrame(kde_model.resample(N_DATA_GEN).transpose(1, 0))
                elif args.gan_method == 'TVAE' or args.gan_method == 'CTGAN':
                    samples = syn_model.sample(N_DATA_GEN)
                    samples_val = syn_model.sample(N_DATA_GEN)
                elif args.gan_method == 'adsgan-tf':
                    class adsargs(object):
                        def __init__(self,):
                            self.iterations = 10000
                            self.h_dim = 30
                            self.z_dim = 10
                            self.mb_size = 25
                            self.lamda = args.epsilon_adsgan
                            self.training_size = SIZE_PARAM
                    adsargs = adsargs()
                    # Calls main function
                    orig_data, synth_data_list, measures = exp_main(adsargs, df)
                    samples = pd.DataFrame(np.asarray(synth_data_list).reshape(-1, dataset.shape[1])[:N_DATA_GEN])
                    samples_val = pd.DataFrame(np.asarray(synth_data_list).reshape(-1, dataset.shape[1])[N_DATA_GEN:2*N_DATA_GEN])
                else:  # synthcity
                    samples = syn_model.generate(count=N_DATA_GEN)
                    samples_val = syn_model.generate(count=N_DATA_GEN)

                #eval_met = evaluate(pd.DataFrame(samples), df)
                #eval_met = compute_metrics(samples, dataset[:N_DATA_GEN], which_metric = ['WD'])['wd_measure']
                wd_n = min(len(samples), len(addition_set))
                eval_met_on_held_out = compute_metrics(samples[:wd_n], addition_set[:wd_n], which_metric=['WD'])['wd_measure']
                #eval_ctgan = evaluate(samples, pd.DataFrame(addition_set2))
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_evaluation'] = (eval_met_on_held_out)
                print('SIZE: ', SIZE_PARAM,
                      'TVAE EPOCH: ', TRAINING_EPOCH,
                      'N_DATA_GEN: ', N_DATA_GEN,
                      'ADDITION_SIZE: ', ADDITION_SIZE,
                      'Performance (Sample-Quality): ', eval_met_on_held_out)
                
                np.save(f'synth_folder/{args.gpu_idx}_synth_samples', samples)
                np.save(f'synth_folder/{args.gpu_idx}_training_set', training_set)
                np.save(f'synth_folder/{args.gpu_idx}_test_set', test_set)
                np.save(f'synth_folder/{args.gpu_idx}_ref_set1', addition_set)
                np.save(f'synth_folder/{args.gpu_idx}_ref_set2', addition_set2)
                
                ''' 4. density estimation / evaluation of Eqn.(1) & Eqn.(2)'''
                if args.density_estimator == "bnaf":
                    print(args.device, device)
                    _gen, model_gen = density_estimator_trainer(samples.values, samples_val.values[:int(0.5*N_DATA_GEN)], samples_val.values[int(0.5*N_DATA_GEN):], args=args)
                    _data, model_data = density_estimator_trainer(addition_set, addition_set2[:int(0.5*ADDITION_SIZE)], addition_set2[:int(0.5*ADDITION_SIZE)], args=args)
                    p_G_train = compute_log_p_x(model_gen, torch.as_tensor(training_set).float().to(device)).cpu().detach().numpy()
                    p_G_test = compute_log_p_x(model_gen, torch.as_tensor(test_set).float().to(device)).cpu().detach().numpy()
                elif args.density_estimator == "kde":
                    density_gen = stats.gaussian_kde(samples.values.transpose(1, 0))
                    density_data = stats.gaussian_kde(addition_set.transpose(1, 0))
                    p_G_train = density_gen(training_set.transpose(1, 0))
                    p_G_test = density_gen(test_set.transpose(1, 0))
                elif args.density_estimator == 'prior':
#                     p_G_train = gaussian(samples.values).pdf(training_set)
#                     p_G_test = gaussian(samples.values).pdf(test_set)
                    density_gen = stats.gaussian_kde(samples.values.transpose(1, 0))
                    density_data = stats.gaussian_kde(addition_set.transpose(1, 0))
                    p_G_train = density_gen(training_set.transpose(1, 0))
                    p_G_test = density_gen(test_set.transpose(1, 0))
                X_test_4baseline = np.concatenate([training_set, test_set])
                Y_test_4baseline = np.concatenate([np.ones(training_set.shape[0]), np.zeros(test_set.shape[0])]).astype(bool)
                # build another GAN for hayes and GAN_leak_cal
                ctgan = CTGANSynthesizer(epochs=200)
                samples.columns = [str(_) for _ in range(dataset.shape[1])]
                ctgan.fit(samples)  # train a CTGAN on the generated examples

                ctgan_representation = ctgan._transformer.transform(X_test_4baseline)
                print(ctgan_representation.shape)
                ctgan_score = ctgan._discriminator(torch.as_tensor(ctgan_representation).float().to(device)).cpu().detach().numpy()
                print(ctgan_score.shape)

                acc, auc = compute_metrics_baseline(ctgan_score, Y_test_4baseline)

                X_ref_GLC = ctgan.sample(addition_set.shape[0])

                baseline_results, baseline_scores = baselines(X_test_4baseline,
                                                              Y_test_4baseline,
                                                              samples.values,
                                                              addition_set,
                                                              X_ref_GLC
                                                              )
                baseline_results = baseline_results.append({'name': 'hayes', 'acc': acc, 'auc': auc}, ignore_index=True)
                baseline_scores['hayes'] = ctgan_score
                print('baselines:', baseline_results)
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Baselines'] = baseline_results
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_BaselineScore'] = baseline_scores
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Xtest'] = X_test_4baseline
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Ytest'] = Y_test_4baseline

                # eqn1: \prop P_G(x_i)
                log_p_test = np.concatenate([p_G_train, p_G_test])
                thres = np.quantile(log_p_test, 0.5)
                auc_y = np.hstack((np.array([1]*training_set.shape[0]), np.array([0]*test_set.shape[0])))
                fpr, tpr, thresholds = metrics.roc_curve(auc_y, log_p_test, pos_label=1)
                auc = metrics.auc(fpr, tpr)

                print('Eqn.(1), training set prediction acc', (p_G_train > thres).sum(0) / SIZE_PARAM)
                print('Eqn.(1), AUC', auc)
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn1'] = (p_G_train > thres).sum(0) / SIZE_PARAM
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn1AUC'] = auc
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn1Score'] = log_p_test
                # eqn2: \prop P_G(x_i)/P_X(x_i)
                if args.density_estimator == "bnaf":
                    p_R_train = compute_log_p_x(model_data, torch.as_tensor(training_set).float().to(device)).cpu().detach().numpy()
                    p_R_test = compute_log_p_x(model_data, torch.as_tensor(test_set).float().to(device)).cpu().detach().numpy()
                    log_p_rel = np.concatenate([p_G_train-p_R_train, p_G_test-p_R_test])
                elif args.density_estimator == "kde":
                    p_R_train = density_data(training_set.transpose(1, 0)) + 1e-30
                    p_R_test = density_data(test_set.transpose(1, 0)) + 1e-30
                    log_p_rel = np.concatenate([p_G_train/p_R_train, p_G_test/p_R_test])
                elif args.density_estimator == 'prior':
                    p_R_train = norm.pdf(training_set)# + 1e-30
                    #density_data(training_set.transpose(1, 0)) + 1e-30
                    p_R_test = norm.pdf(test_set)# + 1e-30
                    #density_data(test_set.transpose(1, 0)) + 1e-30
                    log_p_rel = np.concatenate([p_G_train/p_R_train, p_G_test/p_R_test])
                

                thres = np.quantile(log_p_rel, 0.5)
                auc_y = np.hstack((np.array([1]*training_set.shape[0]), np.array([0]*test_set.shape[0])))
                fpr, tpr, thresholds = metrics.roc_curve(auc_y, log_p_rel, pos_label=1)
                auc = metrics.auc(fpr, tpr)
                if args.density_estimator == "bnaf":
                    print('Eqn.(2), training set prediction acc', (p_G_train-p_R_train >= thres).sum(0) / SIZE_PARAM)
                    print('Eqn.(2), AUC', auc)
                    performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn2'] = (p_G_train-p_R_train > thres).sum(0) / SIZE_PARAM
                elif args.density_estimator == "kde":
                    print('Eqn.(2), training set prediction acc', (p_G_train/p_R_train >= thres).sum(0) / SIZE_PARAM)
                    print('Eqn.(2), AUC', auc)
                    performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn2'] = (p_G_train/p_R_train > thres).sum(0) / SIZE_PARAM
                elif args.density_estimator == 'prior':
                    print('Eqn.(2), training set prediction acc', (p_G_train/p_R_train >= thres).sum(0) / SIZE_PARAM)
                    print('Eqn.(2), AUC', auc)
                    performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn2'] = (p_G_train/p_R_train > thres).sum(0) / SIZE_PARAM
                #print('Eqn.(2), test set prediction acc', (p_G_test-p_R_test > thres).sum(0) / SIZE_PARAM)

                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn2AUC'] = auc
                performance_logger[f'{SIZE_PARAM}_{TRAINING_EPOCH}_{ADDITION_SIZE}'][f'{N_DATA_GEN}_Eqn2Score'] = log_p_rel

                if args.gan_method == 'adsgan':
                    np.save(f'results_folder/Oct12_logger_{alias}.npy', performance_logger)
                elif args.gan_method == 'pategan':
                    np.save(f'results_folder/Oct12_logger_{alias}.npy', performance_logger)
                else:
                    np.save(f'results_folder/Oct12_logger_{alias}.npy', performance_logger)
