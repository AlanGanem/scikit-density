# scikit-density
> skdensity is a package for non parametric conditional density estimation using common machine learning algorithms.


## Conditional probability density estimation (CDE)

skdensity has 3 main estimator types:

- `EntropyEstimator`
    - Quantizes the output space and performs a regression task on the binned (donwsampled )target. During inference (sampling), retrieve the `predict_proba` method and draw samples from bins (upsampling) according to their probabilities. Any estimator (ensemble as well) with the `predict_proba` method can be used as base estimator.
    
- `KernelTreeEstimator`
    - Trains a tree regressor (or ensemble) on train data and saves a mapping of the data in each terminal node. During inference, perform the `apply` method of the base estimator and draws samples from the terminal nodes the infered data ended up
- `KernelTreeEntropyEstimator`
    - same as `KernelTreeEstimator`, but fits a binned tree classifier (just like in `EntropyEstimator`) instead.


## Kernel Density Estimation

## CDE validation metrics

## Install

`pip install your_project_name`

## How to use

Fill me in please! Don't forget code examples:

```python
1+1
```




    2


