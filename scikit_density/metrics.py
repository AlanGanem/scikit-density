# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/04_metrics.ipynb (unless otherwise specified).

__all__ = ['kde_entropy', 'kde_likelihood', 'quantile', 'quantile_sklearn', 'theoretical_entropy', 'marginal_variance',
           'covariance_matrix', 'bimodal_split', 'mad', 'bimodal_variance', 'gaussian_distance_entropy',
           'expected_distance_gaussian_likelihood', 'distance_gaussian_likelihood', 'make_outlier_filter',
           'filter_borders']

# Cell
import numpy as np
from sklearn.metrics import pairwise
from scipy import stats
from sklearn.preprocessing import QuantileTransformer

from .core.random_variable import KDE, RandomVariable
from .utils import (
    _fix_one_sample_2d, _fix_one_dist_2d, _fix_dist_1d,
    _fix_X_1d, _assert_dim_3d, _assert_dim_1d, _assert_dim_2d, _fix_one_dist_1d
)


# Cell
def kde_entropy(data, sample_size = 10000, **kde_kwargs):
    '''
    Calculates the entropy of multiple continuous distributions. entropy equals np.mean(-np.log(p(x)))
    input should be of shape (n_distributions, n_sample_per_distribution, n_dims_in_distribtuion)
    '''
    data = _assert_dim_3d(data)
    return np.array([KDE(**kde_kwargs).fit(d).entropy(sample_size = sample_size) for d in data])

# Cell
def kde_likelihood(y_true,samples, **kde_kwargs):
    '''
    Calculates the likelihood of y_true in kde estimation of samples
    input should be of shape (n_distributions, n_sample_per_distribution, n_dims_in_distribtuion)
    '''
    data = _assert_dim_3d(samples)
    return np.array([KDE(**kde_kwargs).fit(samples[i]).evaluate(y_true[i:i+1]) for i in range(samples.shape[0])])

# Cell
def quantile(y_true, pred_dist):
    '''checks in which quantile lies y_true, given the predicted distribution'''
    y_true = _fix_X_1d(y_true)
    y_true = _fix_one_sample_2d(y_true)
    pred_dist = _assert_dim_3d(pred_dist)
    assert y_true.shape[0] == pred_dist.shape[0], 'number of dists should be the same as number of points'
    return _fix_one_dist_2d(np.array([(y_true[i].T >= pred_dist[i].T).mean(axis = 1) for i in range(len(y_true))]))

# Cell
def quantile_sklearn(y_true, pred_dist):
    '''checks in which quantile lies y_true, given the predicted distribution, using skleaerns QuantileTransformer'''
    y_true = _fix_X_1d(y_true)
    y_true = _fix_one_sample_2d(y_true)
    assert y_true.shape[0] == pred_dist.shape[0], 'number of dists should be the same as number of points'
    return np.array([QuantileTransformer().fit(pred_dist[i]).transform(y_true[i]) for i in range(pred_dist.shape[0])])

# Cell
def theoretical_entropy(data, dist = 'norm'):
    '''
    returns the entropy of the maximum likelihood estiation of `dist` given `data`
    dist should be one dimensional for cases when `dist` != 'kde'
    '''
    data = _assert_dim_3d(data)
    return np.array([RandomVariable(d).fit_dist(dist).entropy(dist) for d in data])

# Cell
def marginal_variance(data):
    '''
    Calculates the variance for each dimension (marginal) of multiple distributions
    input should be of shape (n_distributions, n_sample_per_distribution, n_dims_in_distribtuion)
    '''
    data = _assert_dim_3d(data)
    return data.var(axis = -2)

# Cell
def covariance_matrix(data):
    '''
    Calculates the variance for each dimension (marginal) of multiple distributions
    input should be of shape (n_distributions, n_sample_per_distribution, n_dims_in_distribtuion)
    '''
    raise NotImplementedError

# Cell
def bimodal_split(data, filter_size = 3, lb = 0.1,ub = 0.9):
    '''
    reutrns siplitting point of single distribution in two according to the highest value of the derivative of cpdf
    '''

    _assert_dim_1d(data)
    filter_size = int(np.ceil(filter_size)) if filter_size >= 1 else int(max(1,np.ceil(data.shape[0]*filter_size)))
    data.sort()
    data = filter_borders(data,lb,ub)
    diff = np.diff(data)
    v = np.ones(filter_size)/filter_size
    diff = np.convolve(a = diff,v = v, mode = 'same')
    argmax = np.argmax(diff)
    split_point = (data[min(data.shape[0] - 1,argmax + filter_size)] + data[argmax])/2
    return split_point

# Cell
def mad(data):
    '''
    calculates mean average deviance (a robust version of standard deviation)
    '''
    np.median(np.absolute(data - np.mean(data)))
    pass

# Cell
def bimodal_variance(data, filter_size = 0.05, lb = 0.1,ub = 0.9):
    '''
    returns weighted marginal variance of splitted data in two according to the highest value of the derivative of cpdf
    returns a variance array of shape (n_dists, n_dims)
    '''
    data = _assert_dim_3d(data)
    #make split point
    #GENERALIZE FOR MULTIDIM
    mses = []
    for dist in range(data.shape[0]):
        mses.append([])
        for dim in range(data.shape[2]):
            d = data[dist,:,dim]
            split_point = bimodal_split(d, filter_size, lb ,ub)
            arr1, arr2 = d[d >= split_point], d[d < split_point]
            mses[dist].append((arr1.shape[0]*(arr1.var()) + arr2.shape[0]*(arr2.var()))/d.shape[0])
    #average variance
    return np.array(mses)

# Cell
def gaussian_distance_entropy(data):
    '''
    calculates the entropy of the distribution of distances from centroid of points in dist, assuming normal distribution
    '''
    return -np.log(expected_distance_gaussian_likelihood(data))

# Cell
def expected_distance_gaussian_likelihood(data):
    '''
    calculates the expected likelihood of the distances from centroid of samples in distributions in dist
    input should be of shape (n_distributions, n_sample_per_distribution, n_dims_in_distribtuion)
    '''
    dist = _assert_dim_3d(data)
    return np.array([distance_gaussian_likelihood(d).mean() for d in data])

# Cell
def distance_gaussian_likelihood(data):
    '''
    calculates the expected likelihood of the distances from the centroid of samples in dist
    '''
    centroid = data.mean(axis = 0).reshape(1,-1)
    distances =  pairwise.euclidean_distances(data, centroid).flatten()
    distance_std = distances.std()
    if distance_std == 0:
        return 1
    z = (distances - distances.mean())/distance_std
    return 1/(distance_std*np.pi**(1/2))*np.exp(-1/2*z**2)

# Cell
def make_outlier_filter(data, lb = 25, ub = 75, c = 1):
    a = np.array(data)
    upper_quartile = np.percentile(a, ub)
    lower_quartile = np.percentile(a, lb)
    iqr = (upper_quartile - lower_quartile) * c
    lb = lower_quartile - iqr
    ub = upper_quartile + iqr
    filter_ = np.zeros(a.shape)
    filter_[(a >= lb) & (a <= ub)] = 1
    return filter_

# Cell
def filter_borders(data, lb = 0.05, ub = 0.95):
    lb = int(len(data)*lb)
    ub = int(len(data)*ub)
    return data[lb:ub]

#def distance_log_variance(dist):
#    '''variance of the distances of points to centroid of distribution'''
#    centroid = dist.mean(axis = 0).reshape(1,-1)
#    distances =  pairwise.euclidean_distances(dist, centroid).flatten()
#    return distances.var()