# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/01_ensemble.ipynb (unless otherwise specified).

__all__ = ['JointEstimator', 'JointEntropyEstimator', 'JointSimilarityTreeEstimator', 'EntropyEstimator',
           'expected_likelihood', 'inverese_log_node_var', 'datapoint_pdf', 'datapoint_gaussian_likelihood',
           'AVALIBLE_NODE_AGG_FUNC', 'AVALIBLE_DATAPOINT_WEIGHT_FUNC', 'EnsembleTreesDensityMixin',
           'SimilarityTreeEnsemble', 'SimilarityTreeEnsembleEntropy', 'BaggingDensityEstimator',
           'AdaBoostDensityEntropyEstimator', 'AdaBoostDensityEstiamtor']

# Cell
from warnings import warn
from functools import partial
import copy
from tqdm.notebook import tqdm

import numpy as np
import pandas as pd
from sklearn import ensemble
from sklearn.base import BaseEstimator
from sklearn.preprocessing import OneHotEncoder, normalize, QuantileTransformer, FunctionTransformer
from sklearn.multioutput import MultiOutputRegressor
from sklearn.utils.fixes import _joblib_parallel_args
from sklearn.metrics import pairwise
from numpy.linalg import LinAlgError
from scipy.spatial.distance import cdist

import scipy
from joblib import Parallel, delayed


from .utils import (cos_sim_query, sample_multi_dim, ctqdm, add_noise,sample_from_dist_array,
                                  DelegateEstimatorMixIn, _fix_X_1d, _fix_one_dist_1d, _fix_one_dist_2d,
                                  _add_n_dists_axis,_add_n_samples_axis,_add_n_dims_axis,sample_idxs
                                 )

from .metrics import kde_entropy, quantile, marginal_variance, bimodal_variance, kde_likelihood, kde_quantile, agg_smallest_distance
from .core.random_variable import KDE

# Cell
class JointEstimator(MultiOutputRegressor):
    '''Custom multioutput for multioutput cases except random forests (which handles multi output directly)'''
    def apply(self,X):
        result = [estim.apply(X) for estim in self.estimators_]
        return np.concatenate(result, axis = -1)
    def sample(self, X, sample_size = 10, weights = None):
        result = np.array([estim.sample(X, sample_size = sample_size, weights = weights) for estim in self.estimators_])
        result = np.swapaxes(result,0,1)
        result = np.swapaxes(result,1,2)
        return result

class JointEntropyEstimator(MultiOutputRegressor):
    '''Custom multioutput for multioutput cases except random forests (which handles multi output directly)'''
    def apply(self,X):
        result = [estim.apply(X) for estim in self.estimators_]
        return np.concatenate(result, axis = -1)
    def sample(self, X, sample_size = 10, weights = None):
        result = np.array([estim.sample(X, sample_size = sample_size, weights = weights) for estim in self.estimators_])
        result = np.swapaxes(result,0,1)
        result = np.swapaxes(result,1,2)
        return result

class JointSimilarityTreeEstimator(MultiOutputRegressor):
    '''Custom multioutput for multioutput estimator for `SimilarityTreesEstiamtor`s'''
    @property
    def y_(self,):
        '''stacked y_ attributes of each estimator (one for each dim)'''
        return np.hstack([_fix_X_1d(estim.y_) for estim in self.estimators_])

    def _similarity_sample_idx(self, X, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0):

        sampled_idxs = np.hstack([
            _fix_X_1d(estim._similarity_sample_idx(X, sample_size, weights, n_neighbors,
                           lower_bound, alpha, beta, gamma)
            ) for estim in self.estimators_
        ])

        return sampled_idxs

    def sample(self, X, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0, noise_factor = 0):

        idxs = self._similarity_sample_idx(
            X, sample_size, weights, n_neighbors,lower_bound, alpha, beta, gamma)

        samples = self.y_[[idx for idx in idxs]]
        #fix ndim if sampling for a single value (1, n_samples, n_dims) instead of (n_samples, n_dims)
        samples = samples if len(samples.shape) != 2 else _add_n_dists_axis(samples)
        # samples will have n_dims*sample_size samples, resample with no replacement to match sample_size
        samples = sample_from_dist_array(samples, sample_size = sample_size, weights = None, replace = False)
        return add_noise(samples, noise_factor)

    def custom_predict(self, X, agg_func, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0):

        samples = self.sample(X, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0)

        return np.array([agg_func(sample) for sample in samples])


# Cell
class EntropyEstimator(BaseEstimator, DelegateEstimatorMixIn):
    '''
    Meanwhile only performs marginal density estiamtion, not joint. Thus, only 1dimensional y.
    For joint, should try something using RegressionChain (to pass dimension information to the prediction of other dims)
    '''
    def __init__(self,estimator, resolution = 200, alpha = 1, bins_dist_kws = {} ,**q_transformer_kws):
        assert hasattr(estimator, 'predict_proba'), 'estimator should have `predict_proba` method'
        self.estimator = estimator
        self.q_transformer = QuantileTransformer(**q_transformer_kws) #<-- pass object as argument??
        self.alpha = alpha
        self.resolution = resolution
        self.bins_dist_kws = bins_dist_kws
        return

    def _q_transformer_fit(self, y):
        '''
        fits self.q_transformer
        '''
        y = _fix_X_1d(y)
        self.q_transformer.fit(y)
        return self.q_transformer

    def _q_transformer_transform(self, y):
        '''
        maps floats to int (bin_id in histogram)
        '''
        y = _fix_X_1d(y)
        y_transformed = self.q_transformer.transform(y)
        y_transformed = np.around(y_transformed*(self.resolution - 1), decimals = 0).astype(int)
        return y_transformed.flatten()

    def _q_transformer_inverse_transform(self,y):
        '''
        maps from bin_id in histogram (int) to float.
        beware that during transform, information is lost due to downsampling, so inverse_transform will
        not be an exact inverse_transform.
        '''
        y = _fix_X_1d(y)
        y_transformed = (y/(self.resolution - 1)).astype(float)
        return self.q_transformer.inverse_transform(y_transformed).flatten() #1d asserted already

    def fit(self, X, y = None, **estimator_fit_kws):
        #set y_dim
        if len(y.shape) == 1:
            self.y_dim = 1
        elif len(y.shape) == 2:
            # assert 1d
            assert self.y_dim[-1] == 1, 'y should be 1d. For joint estimation use JointOutputEstimator'
            self.y_dim = y.shape[-1]
        else:
            raise AssertionError('y should be 1d vector or 2d column array (n_samples,1)')
        #reshape when y.dim == 1 and array dim equals 2
        if self.y_dim == 1:
            y = y.reshape(y.shape[0])

        self._q_transformer_fit(y)
        # Fit one instance of RandomVariable or KDE for each bin:
        y_transformed = self._q_transformer_transform(y)
        bin_ids = list(set(y_transformed))
        bins_data_mapper = [y[y_transformed == i] for i in bin_ids]
        self._bin_dist_estimators = [KDE(**self.bins_dist_kws).fit(d) for d in bins_data_mapper]
        #fit classifier
        self.estimator.fit(X = X, y = y_transformed, **estimator_fit_kws)
        return self

    def _get_bin_pdf(self,X):
        '''
        returns pdf array of shape (n_dists, n_bins, n_dims)
        the values are the probability "density" for that bin
        '''
        probas = self.estimator.predict_proba(X)
        probas = np.array(probas)
        return probas

    def custom_predict(self, X):
        pass

    def _rv_bin_sample(self, bin_probas, sample_size):
        '''
        Generate RV samples from bins of 1 observation
        '''
        assert len(bin_probas.shape) == 2, f'Passed weights array should be 2d not {bin_probas.shape}'
        #sample_sizes = np.round(sample_size*weights_array,0)
        #delta_sample_sizes = sample_size - sample_sizes.sum(axis = 0)
        # make sample_sizes sum up to sample_size <- there might be a better way to do it
        #assert delta_sample_sizes >= 0, 'sample_size sanity check not passed, delta negative'
        #if delta_sample_sizes > 0:
        #    idxs = sample_idxs(weights_array, sample_size = delta_sample_sizes)
        #    idxs, counts = numpy.unique(a, return_counts=True)
        #    for i in range(idxs.shape[0]):
        #        sample_sizes[idxs[i]] += counts[i]
        #SAMPLE ALL KDES AND THE SAMPLE FROM SAMPLED ARRAY
        samples_kde = np.array([bin_dist.sample(sample_size) for bin_dist in self._bin_dist_estimators])
        samples_kde = samples_kde[:,:,0]
        idxs = sample_idxs(bin_probas, sample_size = sample_size)
        samples = []

        for i in tqdm([*range(bin_probas.shape[0])]):
            idx = idxs[i]
            idx, counts = np.unique(idx, return_counts = True)

            s = [np.random.choice(samples_kde[i],c, replace = True) for i,c in zip(idx,counts)]
            #s = [self._bin_dist_estimators[vc[0]].rvs(sample_size = vc[1]).flatten() for vc in value_counts]
            samples.append(np.concatenate(s))
            #samples.append(np.concatenate(s))
        return np.array(samples)

    def sample(self, X, sample_size = 100, weight_func = None, alpha = None, replace = True, noise_factor = 0):
        '''
        weight func is a function that takes weight array (n_dists, n_bins) and returned
        an array of the same shape but with desired processing of the weights. if weight_func is not None,
        alpha is ignored
        '''
        #set alpha if not None, else use self.alpha
        alpha = alpha if not alpha is None else self.alpha

        #apply weight_func if not None, else, power to alpha
        bins_probas = self._get_bin_pdf(X)

        if self.y_dim == 1:
            bins_probas = _add_n_dists_axis(bins_probas)

        bins_probas = _fix_X_1d(bins_probas)
        # for 1d case
        bins_probas = bins_probas[0,:,:]
        if not weight_func is None:
            bins_probas = normalize(weight_func(bins_probas), norm  = 'l1')
        else:
            bins_probas = normalize(bins_probas**alpha, norm = 'l1')

        #samples = []
        #for dim_dist in bins_probas:
        #    dim_dist = _fix_X_1d(dim_dist)
        #    if not weight_func is None:
        #        bin_probas = normalize(weight_func(dim_dist), norm  = 'l1')
        #    else:
        #        bin_probas = normalize(dim_dist**alpha, norm = 'l1')

        #    sampled_bins = sample_idxs(bin_probas, sample_size, replace)
            #reshape in order to work with the QuantileTransformer inverse_transform foe each iteration
            #sampled_bins = sampled_bins.reshape(*sampled_bins.shape, 1)
            #samples.append(sampled_bins)

        #samples = np.array([self._q_transformer_inverse_transform(sb) for sb in samples])
        #samples = np.array(samples)
        #samples = np.moveaxis(samples, 2,1)
        #samples = np.moveaxis(samples, 0,2)

        #samples = np.array([self._q_transformer_inverse_transform(s) for s in samples])
        samples = self._rv_bin_sample(bins_probas, sample_size)
        samples = _add_n_dims_axis(samples) # make a 3d sample array with dim axis = 1
        return add_noise(samples, noise_factor)

    def score(self, X, y = None, **score_kws):
        return self.estimator.score(X, self._q_transformer_transform(y), **score_kws)


# Cell
#node quality functions
def expected_likelihood(node_data, sample_size = 100):
    kde = KDE().fit(node_data)
    return np.mean(kde.evaluate(kde.rvs(sample_size = sample_size)))

def inverese_log_node_var(node_data):  #makes no sense for multivariate distribtuions
    centroid = node_data.mean(axis = 0).reshape(1,-1)
    distances =  cdist(node_data, centroid, 'seuclidean').flatten()
    return 1/np.log1p(np.mean(distances))


# datapoint-node functions
def datapoint_pdf(node_data):
    return KDE().fit(node_data).pdf(node_data)

def datapoint_gaussian_likelihood(node_data):
    centroid = node_data.mean(axis = 0).reshape(1,-1)
    distances =  cdist(node_data, centroid, 'seuclidean').flatten()
    distance_std = distances.std()
    #if distance_std == 0:
    #    return 1
    z = (distances - distances.mean())/distance_std
    return 1/(distance_std*np.pi**(1/2))*np.exp(-1/2*z**2)

def _bimodal_variance_fix_dim(x):
    if len(x.shape) == 1:
        return 1/np.log1p(bimodal_variance(_fix_one_dist_1d(x)))
    else:
        return 1/np.log1p(bimodal_variance(_fix_one_dist_2d(x)))


AVALIBLE_NODE_AGG_FUNC = {
    'expected_likelihood':expected_likelihood,
    'inverse_log_variance':inverese_log_node_var,
    'inverse_log_bimodal_variance': _bimodal_variance_fix_dim
}

AVALIBLE_DATAPOINT_WEIGHT_FUNC = {
    'kde_likelihood': datapoint_pdf,
    'gaussian_likelihood': datapoint_gaussian_likelihood
}

# Cell
class EnsembleTreesDensityMixin():

    '''Base Class containing important methods for building Naive and Similarity Density Tree estimators'''

    @property
    def _node_data_generator(self):
        return self._make_node_data_generator(self.y_, self._raw_leaf_node_matrix)

    def _make_node_kde_array(self): #<- since kde esitmation is the best approach, save kde fitted instances for each node
        #to make use of it during node and node_data wieght inference
        #maybe its better to get data from multiple nodes before fitting kde
        raise NotImplementedError

    def _make_node_cdist_array(self): #<- gaussian likelihood works fine as well, so save cdist matrix for each node
        raise NotImplementedError

    def _apply(self, X):
        '''
        A substitute for estimator.apply in case it returns 3d arrays (such as sklearns gradient boosting classifier)
        instead of 2d. In case returned array from estimator.apply returns a 2dim array, the returned value of the function
        is the same as the returned array of self.estimator.apply
        '''
        applied_arr = self.estimator.apply(X)
        dim1_shape = applied_arr.shape[0]
        dim2_shape = np.prod(applied_arr.shape[1:])
        return applied_arr.reshape(dim1_shape, dim2_shape)

    def _fit_leaf_node_matrix(self, X, y, node_rank_func, node_data_rank_func):
        nodes_array = self._apply(X)
        encoder = OneHotEncoder()
        leaf_node_matrix = encoder.fit_transform(nodes_array)

        self._raw_leaf_node_matrix = leaf_node_matrix
        #self._node_data_generator = self.#self._make_node_data_generator(y, leaf_node_matrix)
        self._leaf_node_weights = self._calculate_node_weights(y, leaf_node_matrix, node_rank_func)
        self._encoder = encoder
        self._leaf_node_matrix = self._make_weighted_query_space(y, leaf_node_matrix, node_data_rank_func)# <- try making this a property
        return self

    def _transform_query_matrix(self, X):

        return  self._make_weighted_query_vector(
            agg_node_weights = self._leaf_node_weights,
            node_matrix = self._encoder.transform(self._apply(X)))


    def _query_idx_and_sim(self, X, n_neighbors, lower_bound, beta, gamma):
        idx, sim = cos_sim_query(
            self._transform_query_matrix(X), self._leaf_node_matrix, n_neighbors=n_neighbors,
            lower_bound=lower_bound, beta = beta, gamma = gamma)
        return idx, sim


    def _kde_similarity_sample(self, X, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0, noise_factor = 1e-6, **kde_kwargs):

        idx, sim = self._query_idx_and_sim(X ,n_neighbors=n_neighbors, lower_bound=lower_bound,beta = beta, gamma = gamma)
        idx, sim = np.array(idx), np.array(sim)

        p = self._handle_sample_weights(weight_func = weights, sim = sim, alpha = alpha)
        samples = []
        if noise_factor == 'auto':
            for i in range(len(idx)):
                ys = self.y_[sample_multi_dim(idx[i], sample_size = sample_size, weights = p[i], axis = 0)]
                noise = agg_smallest_distance(ys.reshape(1,*ys.shape), agg_func = np.std)
                ys = add_noise(ys, noise)
                samples.append(KDE(**kde_kwargs).fit(ys, sample_weight = None).sample(sample_size = sample_size))
        else:
            for i in range(len(idx)):
                ys = self.y_[sample_multi_dim(idx[i], sample_size = sample_size, weights = p[i], axis = 0)]
                ys = add_noise(ys, noise_factor)
                ys = KDE(**kde_kwargs).fit(ys, sample_weight = None).sample(sample_size = sample_size)
                samples.append(ys)

        for i in range(len(idx)):
            ys = self.y_[sample_multi_dim(idx[i], sample_size = sample_size, weights = p[i], axis = 0)]
            noise = agg_smallest_distance(ys.reshape(1,*ys.shape), agg_func = np.std)
            ys = add_noise(ys, noise)


            #try

        return np.array(samples)

    def _similarity_sample(self, X, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0, noise_factor = 'auto'):

        idx, sim = self._query_idx_and_sim(X ,n_neighbors=n_neighbors, lower_bound=lower_bound,beta = beta, gamma = gamma)
        idx, sim = np.array(idx), np.array(sim)

        p = self._handle_sample_weights(weight_func = weights, sim = sim, alpha = alpha)
        samples = []
        if noise_factor == 'auto':
            for i in range(len(idx)):
                ys = self.y_[sample_multi_dim(idx[i], sample_size = sample_size, weights = p[i], axis = 0)]
                noise = agg_smallest_distance(ys.reshape(1,*ys.shape), agg_func = np.std)
                ys = add_noise(ys, noise)
                samples.append(ys)
        else:
            for i in range(len(idx)):
                ys = self.y_[sample_multi_dim(idx[i], sample_size = sample_size, weights = p[i], axis = 0)]
                samples.append(add_noise(ys, noise_factor))

        return np.array(samples)

    def _similarity_sample_idx(self, X, sample_size = 100, weights = None, n_neighbors = 10,
                           lower_bound = 0.0, alpha = 1, beta = 0, gamma = 0):

        idxs, sim = self._query_idx_and_sim(X ,n_neighbors=n_neighbors, lower_bound=lower_bound,beta = beta, gamma = gamma)
        idxs, sim = np.array(idxs), np.array(sim)

        p = self._handle_sample_weights(weight_func = weights, sim = sim, alpha = alpha)

        samples_idxs = sample_from_dist_array(idxs.reshape(*idxs.shape,1), sample_size, p)
        samples_idxs = samples_idxs.reshape(samples_idxs.shape[:-1])
        return samples_idxs

    def _similarity_empirical_pdf(self, X, weights, n_neighbors, lower_bound, alpha, beta, gamma):

        idx, sim = cos_sim_query(
            self._transform_query_matrix(X),
            self._leaf_node_matrix,
            n_neighbors=n_neighbors,
            lower_bound=lower_bound,
            beta = beta,
            gamma = gamma)
        p = self._handle_sample_weights(weight_func = weights, sim = sim, alpha = alpha)
        return np.array([self.y_[i] for i in idx]), p

    def _custom_predict(self, X, agg_func, sample_size, weights, n_neighbors, lower_bound, alpha, beta, gamma):
        '''
        performs aggregation in a samples drawn for a specific X and returns the custom predicted value
        as the result of the aggregation. Could be mean, mode, median, std, entropy, likelihood...
        note that agg_func recieves an array of shape (n_samples, n_dims). If you want to perform
        aggregation along dimensions, dont forget to tell agg_func to perform operations along axis = 0
        '''

        samples = self._similarity_sample(X, sample_size, weights, n_neighbors, lower_bound, alpha, beta, gamma)
        return np.array([agg_func(sample) for sample in samples])

    def _calculate_node_weights(self, y, node_matrix, node_rank_func):
        '''
        calculates node weights that maultiplies the query space matrix, in order to make some nodes more relevant
        according to some target data node agg metric.
        input should be a list containing array of node samples as each one of its elements
        '''

        if not node_rank_func is None:
            # cannot call in a vectorized fashion because data from nodes may have different sizes
            #node_weights = Parallel(n_jobs=-1, verbose=0,
            #                   **_joblib_parallel_args(prefer="threads"))(
            #    delayed(node_rank_func)(X)
            #    for X in self._node_data_generator)
            node_weights = [node_rank_func(X) for X in self._node_data_generator]

        else:
            node_weights = np.ones(node_matrix.shape[1])

        return np.array(node_weights)

    def _calculate_node_datapoint_weights(self, y, node_matrix, node_data_rank_func):
        '''
        Calculates node-datapoint(y values) weights. higher values meansa datapoint "belongs tighter"
        to that point and is more loleky to be sampled when that node is reached. some cases of node-datapount wieghts
        could be the likelihood of that point given the node pdf, or some sort of median/mean deviance from point to node samples
        '''
        #datapoint_node_weights = Parallel(n_jobs=1, verbose=0,
        #                   **_joblib_parallel_args(prefer="threads"))(
        #    delayed(node_data_rank_func)(X)
        #    for X in node_data_generator)

        datapoint_node_weights = [node_data_rank_func(node_data) for node_data in self._node_data_generator]
        return datapoint_node_weights

    def _make_node_data_generator(self, y, node_matrix):
        s1 = node_matrix.sum(axis = 0).cumsum().A.astype(int).flatten()
        s2 = np.concatenate([[0],s1[:-1]])
        slices = [slice(i[0],i[1]) for i in zip(s2,s1)]
        idxs = node_matrix.tocsc().indices
        idxs = [idxs[s] for s in slices]
        return (y[idx] for idx in tqdm(idxs))

    def _handle_sample_weights(self, weight_func, sim, alpha):
        '''
        sampling wights should sum to 1, since its a sampling probability
        '''
        if weight_func is None:
            return np.array([normalize((i**alpha).reshape(1,-1), norm = 'l1').flatten() for i in sim])
        else:
            return np.array([normalize((weight_func(i)).reshape(1,-1), norm = 'l1').flatten() for i in sim])

    def _make_weighted_query_vector(self, agg_node_weights, node_matrix):
        '''
        multiplies elements of query vector by their respective weights
        the greater the weights, the better the "quality" of the nodes
        '''
        assert isinstance(node_matrix, scipy.sparse.csr_matrix), 'input should be instance of scipy.sparse.csr_matrix'
        node_matrix.data = node_matrix.data*np.take(agg_node_weights, node_matrix.indices)
        return node_matrix

    def _make_weighted_query_space(self, y, node_matrix, node_data_rank_func = None):
        '''
        query space is the leaf_node_matrix multiplied by node_data_weights
        the greater the value in the matrix, the better the "quality" of that data point
        '''
        assert isinstance(node_matrix, scipy.sparse.csr_matrix), 'input should be instance of scipy.sparse.csr_matrix'

        if not node_data_rank_func is None:
            # datapoint_node_weights multiplication (columns)
            #make copy
            node_matrix = copy.deepcopy(node_matrix)
            #cast to csc to make .data order columnwise
            node_matrix = node_matrix.tocsc()
            datapoint_node_weights = self._calculate_node_datapoint_weights(y, node_matrix, node_data_rank_func)
            node_matrix.data = node_matrix.data*np.concatenate(datapoint_node_weights)
            #convert back to csr
            node_matrix = node_matrix.tocsr()
        else:
            pass

        return node_matrix

# Cell

class SimilarityTreeEnsemble(BaseEstimator, DelegateEstimatorMixIn ,EnsembleTreesDensityMixin):

    def __init__(self, estimator, alpha = 1, beta = 1, gamma = 1, node_rank_func = None,
                 node_data_rank_func = None,n_neighbors = 30, lower_bound = 0.0):

        assert estimator.min_samples_leaf >= 3, 'min_samples_leaf should be greater than 2'

        self.estimator = estimator
        self.n_neighbors = n_neighbors
        self.lower_bound = lower_bound
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma

        if node_rank_func is None:
            self.node_rank_func = node_rank_func
        else:
            try: self.node_rank_func = node_rank_func if callable(node_rank_func) else AVALIBLE_NODE_AGG_FUNC[node_rank_func]
            except KeyError: raise KeyError(f'if not callable, node_rank_func should be one of {list(AVALIBLE_NODE_AGG_FUNC)}, not {node_rank_func}')

        if node_data_rank_func is None:
            self.node_data_rank_func = node_data_rank_func
        else:
            try: self.node_data_rank_func = node_data_rank_func if callable(node_data_rank_func) else AVALIBLE_DATAPOINT_WEIGHT_FUNC[node_data_rank_func]
            except KeyError: raise KeyError(f'if not callable, node_rank_func should be one of {list(AVALIBLE_DATAPOINT_WEIGHT_FUNC)}, not {node_data_rank_func}')

        return

    def __repr__(self):
        return self.__class__.__name__

    def fit(self, X, y = None):
        self.y_ = y
        self.estimator.fit(X,y)
        self._fit_leaf_node_matrix(
            X, y, node_rank_func = self.node_rank_func, node_data_rank_func = self.node_data_rank_func)# <- MAKE NODE WIEGHTED VERSION

        return self

    def kde_sample(self, X, sample_size = 10, weights = None, n_neighbors = None,
               lower_bound = None, alpha = None, beta = None, gamma = None, noise_factor = 1e-6, **kde_kwargs):

        n_neighbors, lower_bound, alpha, beta, gamma = self._handle_similarity_sample_parameters(
            n_neighbors, lower_bound,alpha, beta, gamma)

        samples = super()._kde_similarity_sample(
            X = X, sample_size = sample_size, weights = weights, n_neighbors = n_neighbors,
            lower_bound = lower_bound, alpha = alpha, beta = beta, gamma = gamma, noise_factor = noise_factor, **kde_kwargs
        )
        return samples

    def sample(self, X, sample_size = 10, weights = None, n_neighbors = None,
               lower_bound = None, alpha = None, beta = None, gamma = None, noise_factor = 1e-6):
        '''wieghts should be callable (recieves array returns array of same shape) or None'''
        n_neighbors, lower_bound, alpha, beta, gamma = self._handle_similarity_sample_parameters(
            n_neighbors, lower_bound,alpha, beta, gamma)

        samples = super()._similarity_sample(
            X = X, sample_size = sample_size, weights = weights, n_neighbors = n_neighbors,
            lower_bound = lower_bound, alpha = alpha, beta = beta, gamma = gamma, noise_factor = noise_factor
        )

        return samples

    def custom_predict(self, X, agg_func, sample_size = 100, weights = None, n_neighbors = None, lower_bound = None, alpha = None, beta = None, gamma = None):
        n_neighbors, lower_bound, alpha, beta, gamma = self._handle_similarity_sample_parameters(n_neighbors, lower_bound, alpha, beta, gamma)
        return self._custom_predict(X, agg_func, sample_size, weights, n_neighbors, lower_bound, alpha, beta, gamma)

    def _handle_similarity_sample_parameters(self, n_neighbors, lower_bound, alpha, beta, gamma):

        if n_neighbors is None:
            n_neighbors = self.n_neighbors
        if lower_bound is None:
            lower_bound = self.lower_bound
        if alpha is None:
            alpha = self.alpha
        if beta is None:
            beta = self.beta
        if alpha is None:
            gamma = self.gamma

        return n_neighbors, lower_bound, alpha, beta, gamma

# Cell
class SimilarityTreeEnsembleEntropy(SimilarityTreeEnsemble):
    '''
    An ensemble that learn representitons of data turning target into bins
    '''
    def __init__(self, estimator, resolution = 2, **sim_tree_ensemble_init_args):
        super().__init__(estimator, **sim_tree_ensemble_init_args)
        self.resolution = resolution
    def fit(self, X, y = None):
        self.y_ = y
        #reshape (-1,1) in case of 1d
        y = _fix_X_1d(y)
        #make uniform quantile bins
        self.quantizer = QuantileTransformer().fit(y)
        #transform to classes
        y = np.round(self.quantizer.transform(y), self.resolution).astype(str)
        # fit
        self.estimator.fit(X,y)
        self._fit_leaf_node_matrix(
            X, self.y_, node_rank_func = self.node_rank_func, node_data_rank_func = self.node_data_rank_func)# <- MAKE NODE WIEGHTED VERSION

        return self

# Cell
def _parallel_predict_regression(estimators, estimators_features, X):
    """Private function used to compute predictions within a job."""
    return np.array([estimator.predict(X[:, features])
               for estimator, features in zip(estimators,
                                              estimators_features)])

class BaggingDensityEstimator(ensemble.BaggingRegressor):

    def sample(self, X, sample_size = 10, weights = None):
        idxs = self._sample_idxs(X, sample_size, weights)
        predictions = self._predict_all_estimators(X)
        return self._sample_from_idxs(predictions, idxs)

    def _predict_all_estimators(self, X):
        ensemble._bagging.check_is_fitted(self)
        # Check data
        X = ensemble._bagging.check_array(
            X, accept_sparse=['csr', 'csc'], dtype=None,
            force_all_finite=False
        )

        # Parallel loop
        n_jobs, n_estimators, starts = ensemble._bagging._partition_estimators(self.n_estimators,
                                                             self.n_jobs)

        all_y_hat = ensemble._bagging.Parallel(n_jobs=n_jobs, verbose=self.verbose)(
            ensemble._bagging.delayed(_parallel_predict_regression)(
                self.estimators_[starts[i]:starts[i + 1]],
                self.estimators_features_[starts[i]:starts[i + 1]],
                X)
            for i in range(n_jobs))

        predictions = np.swapaxes(all_y_hat[0], 0, 1)
        return predictions

    def _sample_from_idxs(self, predictions, idxs):
        return np.array([predictions[i][idxs[i]] for i in range(len(idxs))])

    def _sample_idxs(self, X, sample_size, weights):
        '''Sample indxs according to estimator weights'''
        return [np.random.choice([*range(self.n_estimators)], size = sample_size, p = weights) for i in range(X.shape[0])]


# Cell
class AdaBoostDensityEntropyEstimator:
    pass

class AdaBoostDensityEstiamtor(ensemble.AdaBoostRegressor):

    def sample(self, X, sample_size = 10, weights = 'boosting_weights'):
        idxs = self._sample_idxs(X, sample_size, weights)
        predictions = self._predict_all_estimators(X)
        return self._sample_from_idxs(predictions, idxs)

    def _predict_all_estimators(self, X):
        return np.array([est.predict(X) for est in self.estimators_[:len(self.estimators_)]]).T

    def _sample_from_idxs(self, predictions, idxs):
        return np.array([predictions[i][idxs[i]] for i in range(len(idxs))])

    def _sample_idxs(self, X, sample_size, weights):
        '''Sample indxs according to estimator weights'''

        if weights is None:
            weights = np.ones(sample_size)[:len(self.estimators_)]
            weights /= weights.sum()

        elif weights == 'boosting_weights':
            weights = self.estimator_weights_[:len(self.estimators_)]
            weights /= weights.sum()
        else:
            weights = self.estimator_weights_[:len(self.estimators_)]*weights
            weights /= weights.sum()

        idxs = [np.random.choice([*range(len(self.estimators_))], size = sample_size, p = weights) for i in range(X.shape[0])]
        return idxs

