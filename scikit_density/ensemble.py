# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/01_ensemble.ipynb (unless otherwise specified).

__all__ = ['EnsembleTreesDensityMixin', 'SimilarityTreeEnsemble', 'BaggingDensityEstimator', 'AdaBoostDensityEstiamtor']

# Cell
from warnings import warn
from functools import partial

import numpy as np
import pandas as pd
from sklearn import ensemble
from sklearn.preprocessing import OneHotEncoder, normalize, QuantileTransformer, FunctionTransformer
from sklearn.multioutput import MultiOutputRegressor

from .utils import cos_sim_query, sample_multi_dim, ctqdm

# Cell
class EnsembleTreesDensityMixin:
    '''Base Class containing important methods for building Naive and Similarity Density Tree estimators'''
    def _fit_leaf_sample_graph(self, X):
        nodes_array = self.apply(X)
        encoder = OneHotEncoder()
        self.leaf_node_graph = encoder.fit_transform(nodes_array)
        self.encoder = encoder

    def _make_leaf_node_graph(self, X):
        return self.encoder.transform(self.apply(X))

    def _make_leaf_node_data(self, X, y):
        # create node to data mapper
        y = pd.DataFrame(y)
        node_indexes = self.apply(X)
        tree_node_values_mapper_list = []
        for tree in range(node_indexes.shape[1]):
            tree_node_values_mapper_list.append(dict(
                y.assign(_NODE=node_indexes[:, tree]).groupby('_NODE').apply(
                    lambda x: [x[col].values.tolist() for col in x if not col == '_NODE'])))
        return dict(enumerate(tree_node_values_mapper_list))

    def _query_idx_and_sim(self, X, n_neighbors, lower_bound):
        idx, sim = cos_sim_query(
            self._make_leaf_node_graph(X), self.leaf_node_graph, n_neighbors=n_neighbors, lower_bound=lower_bound)
        return idx, sim

    def _similarity_sample(self, X, sample_size = 100, weights = None, n_neighbors = 10, lower_bound = 0.0, alpha = 1):
        idx, sim = self._query_idx_and_sim(X ,n_neighbors=n_neighbors, lower_bound=lower_bound)
        idx, sim = np.array(idx), np.array(sim)

        p = self._handle_sample_weights(weights, sim, alpha)
        samples = []
        for i in range(len(idx)):
            samples.append(self.y_[sample_multi_dim(idx[i], size = sample_size, weights = p[i], axis = 0)])

            #sampled_idxs = np.random.choice(idx[i], size = sample_size, replace = True, p = p[i])
            #samples.append(self.y_[sampled_idxs])

        return np.array(samples)

    def _similarity_empirical_pdf(self, X, weights = None, n_neighbors = 30, lower_bound = 0, alpha = 1):

        idx, sim = cos_sim_query(
            self._make_leaf_node_graph(X),
            self.leaf_node_graph,
            n_neighbors=n_neighbors, lower_bound=lower_bound)
        p = self._handle_sample_weights(weights, sim, alpha)
        return np.array([self.y_[i] for i in idx]), p

    def _sim_predict(self, X, weights, n_neighbors, lower_bound, alpha):
        '''wieghts must be None or callable that operates on similarity values'''

        values, weights = self._similarity_empirical_pdf(X, weights, n_neighbors, lower_bound, alpha)

        y_multioutput = (len(values.shape) - 1) > 1
        if y_multioutput:
            y_dim = values.shape[-1]
            weights = np.repeat(weights, y_dim, axis = -1).reshape(*weights.shape, y_dim)
            return np.average(values, weights = weights, axis = -2)
        else:
            return np.average(values, weights = weights, axis = -1)


    def _handle_sample_weights(self, weights, sim, alpha):
        if weights is None:
            return np.array([normalize((i**alpha).reshape(1,-1) + 1e-9, norm = 'l1').flatten() for i in sim])
        else:
            return np.array([normalize((weights(i)).reshape(1,-1) + 1e-9, norm = 'l1').flatten() for i in sim])

    def _streaming_fit(self, X):
        '''
        Adds new data to leaf nodes, kind of like a posterior
        '''

# Cell
def SimilarityTreeEnsemble(estimator):

    class SimilarityTreeEnsemble(estimator.__class__, EnsembleTreesDensityMixin):

        def __init__(self, alpha = 1, n_neighbors = 30, lower_bound = 0.0):
            super().__init__(**estimator.get_params())
            self.n_neighbors = n_neighbors
            self.lower_bound = lower_bound
            self.alpha = alpha

        def __repr__(self):
            return self.__class__.__name__

        def fit(self, X, y = None):
            super().fit(X,y)
            self._fit_leaf_sample_graph(X)
            self.y_ = y
            return self

        def sample(self, X, sample_size = 10, weights = None, n_neighbors = None, lower_bound = None, alpha = None):
            '''wieghts should be callable (recieves array returns array of same shape) or None'''
            n_neighbors, lower_bound, alpha = self._handle_similarity_sample_parameters(n_neighbors, lower_bound, alpha)

            return super()._similarity_sample(
                X = X, sample_size = sample_size, weights = weights, n_neighbors = n_neighbors,
                lower_bound = lower_bound, alpha = alpha
            )

        def sim_predict(self, X, weights = None, n_neighbors = None, lower_bound = None, alpha = None):
            n_neighbors, lower_bound, alpha = self._handle_similarity_sample_parameters(n_neighbors, lower_bound, alpha)
            return self._sim_predict(X, weights, n_neighbors, lower_bound, alpha)

        def _handle_similarity_sample_parameters(self, n_neighbors, lower_bound, alpha):

            if n_neighbors is None:
                n_neighbors = self.n_neighbors
            if lower_bound is None:
                lower_bound = self.lower_bound
            if alpha is None:
                alpha = self.alpha

            return n_neighbors, lower_bound, alpha

    return SimilarityTreeEnsemble()

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

