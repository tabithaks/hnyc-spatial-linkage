import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
import interpolation.interpolation as interpolation
from copy import deepcopy
from matplotlib import colors as mcolors
import interpolation.sequences as sequences
import interpolation.dataprocessing as dataprocessing

#Store and modify census data post disambiguation and dwelling fillin/conflict resolution
class CensusData:

    def __init__(self, data, ward_col="Ward_Num", dwelling_col="CENSUS_DWELLING_NUM", block_col = "block_num", x_col = "cd_X", y_col = "cd_Y"):

        #hold census data post disambiguation and dwelling fill in/conflict resolution
        self.data = data

        # initialize col names
        self.ward_col = ward_col
        self.dwelling_col = dwelling_col
        self.block_col = block_col
        self.x_col = x_col
        self.y_col = y_col

        #holds data processesed as desired
        self.df = None

    """
    Purpose: Add distance based sequences to dwelling data
    d: maximum distance between dwellings within a sequence
    returns: sequences added to dwelling data
    """
    def get_dwellings_seq(self, d = 0.25):
        dwellings = self.data.groupby([self.ward_col, self.dwelling_col], as_index=False).first()
        dwellings_dropped = dwellings.groupby(self.ward_col, as_index=False).apply(
            lambda x: sequences.col_for_seq(x, X=self.x_col, Y=self.y_col))
        dwellings_dropped.dropna(subset=["dist"], inplace=True)
        return dwellings_dropped.groupby(self.ward_col, as_index=False).apply(
            lambda x: sequences.get_dist_seq(x, d))

    """
    Purpose: Create dataframe of all census records with sequences added in
    d: Maximum distance between dwellings within the same sequence
    tuned: Dataframe of dwelling with sequences -- allows user to feed in dataframe generated during max distance tuning
     if that's done first. If None (default) generates dataframe of dwellings with sequences with provided max distance 
    """
    def census_records_with_seq(self, d = 0.25, tuned = None):
        if tuned:
            dwellings_sequenced = tuned
        else:
            dwellings_sequenced = self.get_dwellings_seq(d)

        census_1850_model = dataprocessing.dwellings_to_all(self.data, dwellings_sequenced,
                                             [self.ward_col, self.dwelling_col, "sequence_id", "num_between",
                                              "sequence_order_enum"],
                                             [self.ward_col, self.dwelling_col])
        census_1850_model.dropna(inplace=True, subset=["sequence_id"])
        self.df = census_1850_model


    def census_dwelling_records_between(self, d = 0.25, column = None, tuned = None):
        if column is None:
            column = self.block_col
        if tuned:
            dwellings_sequenced = tuned
        else:
            dwellings_sequenced = self.get_dwellings_seq(d)

        dwelling_sequence_sames = interpolation.same_next(dwellings_sequenced, column=column)
        all_dwellings = dataprocessing.all_dwellings_sequenced(self.data, dwelling_sequence_sames,
                                                              ward_col=self.ward_col, dwelling_col=self.dwelling_col)
        self.df = interpolation.get_consecutive_dwellings(all_dwellings, column=column)

class Interpolator:

    def __init__(self, census_data, ward, model, feature_names, *args):

        # initialize input
        self.ward = ward #ward within which the interpolator is predicting
        self.model = model #model for prediction
        self.feature_names = feature_names #feature names used for prediction
        self.df = census_data.df[census_data.df[census_data.ward_col] == ward].copy() #get data within ward as a dataframe

        self.y = None #column name of value to predict

        # initialize col names
        self.ward_col = census_data.ward_col
        self.dwelling_col = census_data.dwelling_col
        self.block_col = census_data.block_col
        self.x_col = census_data.x_col
        self.y_col = census_data.y_col

        # results
        self.train_score = None
        self.test_score = None

    """
    Purpose: Get a train test data, with dwellings only present in one or the other
    Stratified: If true stratify sample, if false, don't
    """
    def stratified_train_test(self, stratified = True):
        return interpolation.stratified_train_test(self.df, self.y, self.dwelling_col, stratified)

    """
    Purpose: Target encode train, test data
    Train: train data
    Test: test data
    """
    def target_encoder(self, train, test):
        return interpolation.target_encoder(train, test, self.feature_names,self.y)

    """
    Purpose: Train model, and save train and test scores
    train: train data
    test: test data
    train_y: train data to predict, if None, assumes that this is in the test datasets
    test_y: test data to predict, if None assumeds that this is in the test dataset
    """
    def train_test_model(self, train, test, train_y = None, test_y = None):

        if train_y is None:
            self.model.fit(train.loc[:,self.feature_names], train[self.y])
            self.train_score = self.model.score(train.loc[:,self.feature_names], train[self.y])
            self.test_score = self.model.score(test.loc[:, self.feature_names], test[self.y])

        else:
            self.model.fit(train.loc[:, self.feature_names], train_y)
            self.train_score = self.model.score(train.loc[:, self.feature_names], train_y)
            self.test_score = self.model.score(test.loc[:, self.feature_names], test_y)

    """
    Purpose: Use model for predicting values after training
    data: data to predict on, assumed to have columns in feature_names attribute
    returns: predictions
    """
    def predict(self, data):
        return self.model.predict(data.loc[:,self.feature_names])

    """
    Purpose: reset model, primarily for tuning/development, can be done directly, but use this to add awareness to
    modifications
    model: model to give the function 
    """
    def set_model(self, model):
        self.model = model

    """
    Purpose: reset feature names, primarily for development. Used for awareness to modification. 
    *Note, if using pipeline with column specific preprocessing, this will cause a failure. Must do preprocessing 
    outside of the model, and set model as a model without pipeline, or change pipeline preprocessing columns appropriately
    and set model with new pipeline
    features: list of features to train on
    """
    def set_features(self, features):
        self.feature_names = features

#Predict block number
class BlockInterpolator(Interpolator):
    def __init__(self, census_data, ward, model, feature_names):
        super().__init__(census_data, ward, model, feature_names)
        self.y = self.block_col #object designed to predict block number

#Predict centroids
class CentroidInterpolator(Interpolator):

    def __init__(self, census_data, ward, model, feature_names, clustering_algo, block_centroids):
        super().__init__(census_data, ward, model, feature_names)
        self.y = "cluster" #predicts clustering label generated by clustering algorhtm

        #clustering variables
        self.clustering_algo = clustering_algo #clustering algorithm
        self.block_centroids = block_centroids #nested dictionary {ward:{block:centroids,...}...}

        #Variables to set after clustering
        self.block_cluster_map = None #saves dictionary of {block:cluster} generated through clustering algorithm
        self.clusters = None #saves list of clusters in order of block centroids

    """
    Purpose: Clustering block centroids
    algo_fit: If true don't fit the clustering algorithm, just predict
    """
    def apply_clustering(self,algo_fit=False):

        to_cluster = np.array(list(self.block_centroids[self.ward].values()))

        if algo_fit:
            self.clusters = self.clustering_algo.predict(to_cluster)
        else:
            self.clusters = self.clustering_algo.fit_predict(to_cluster)

        self.block_cluster_map = {block: clust for block, clust in zip(self.block_centroids[self.ward].keys(), self.clusters)}
        self.df["cluster"] = self.df.apply(lambda row: self.block_cluster_map[row[self.block_col]], axis=1)

    """
    Purpose: General tuning of clustering algorithm
    algo: Clustering algorithm to use
    clusteringvis: If true visualize clusters
    model_score: If true train model
    stratified: If true stratify sample when creating training/test sets, irrelevant if model_scores is False
    *Note: assumes model is a pipeline that includes preprocessing
    """
    def clustering_algo_tuning(self, algo, clustervis = True, model_scores = True, stratified = True):
        self.set_clustering_algo(algo)
        self.apply_clustering()
        if clustervis:
            self.clustervis()
        if model_scores:
            train, test = self.stratified_train_test(stratified = stratified)
            self.train_test_model(train, test)


    """
    Purpose: Visualize clustering, points represent census data
    kmeans: If true assumes clustering algorithm is KMeans and plots cluster centroids
    title: Title of visualization, if None uses default
    """
    def clustervis(self, kmeans=False, title=None):
        if self.clusters is None:
            raise AttributeError("Please run apply clustering first")

        #colors = [color for color, i in zip(mcolors.CSS4_COLORS.values(), range(len(np.unique(self.clusters)))) if i < len(np.unique(self.clusters))]
        colors = [plt.rcParams['axes.prop_cycle'].by_key()['color'][x] for x in range(len(np.unique(self.clusters)))]
        fig, ax = plt.subplots(1, 1, figsize=(8, 8))

        for cluster, color in zip(np.unique(self.clusters), colors):
            # get cluster data
            X_subset = self.df[self.df["cluster"] == cluster]
            centroids_subset = np.array(list(self.block_centroids[self.ward].values()))[self.clusters == cluster]

            # graph info
            ax.scatter(x=X_subset.loc[:, self.x_col], y=X_subset.loc[:, self.y_col], s=5, alpha=0.8, label=str(cluster),
                       color=color)
            ax.scatter(centroids_subset[:, 0], centroids_subset[:, 1], marker="*", s=80, color=color)
            if title is not None:
                ax.set_title(title)
            else:
                ax.set_title("Clustered block centroids, Ward {}, 1850".format(self.ward))
        if kmeans:
            ax.scatter(x=self.clustering_algo.cluster_centers_[:, 0], y=self.clustering_algo.cluster_centers_[:, 1], marker="x", c="k", s=50,
                       label="cluster centroids")
        ax.legend(bbox_to_anchor = (1.04, 1), loc = "upper left")
        plt.show()

    """
    Purpose: Handle instability in kmeans results by saving the best model and best score after 100 runs
    n: number of clusters
    *Note assumes model is a pipeline that includes preprocessing
    """
    def kmeans_best(self, n):

        self.set_clustering_algo(KMeans(n))

        score = 0
        best_clusterer = None
        for i in range(100):

            self.apply_clustering()
            train, test = self.stratified_train_test()
            self.train_test_model(train, test)

            if self.test_score > score:
                score = self.test_score
                best_clusterer = deepcopy(self.clustering_algo)

            if i % 50 == 0:
                print("n is {} and it's the {}th iteration".format(n, i))

        return score, best_clusterer

    """
    Purpose: reset clustering algorithm
    clustering_algo: clustering algorithm to set data
    """
    def set_clustering_algo(self, clustering_algo):
        self.clustering_algo = clustering_algo



