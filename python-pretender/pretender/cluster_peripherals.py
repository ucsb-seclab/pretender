import numpy as np
import sys
import logging

from sklearn.cluster import DBSCAN
from sklearn import metrics

logger = logging.getLogger(__name__)

def cluster_peripherals(data):
    mem_locs = np.array(data).reshape(-1, 1)
    db = DBSCAN(eps=0x100, min_samples=1).fit(mem_locs)
    core_samples_mask = np.zeros_like(db.labels_, dtype=bool)
    core_samples_mask[db.core_sample_indices_] = True
    labels = db.labels_

    # Number of clusters in labels, ignoring noise if present.
    n_clusters_ = len(set(labels)) - (1 if -1 in labels else 0)

    print('Estimated number of clusters: %d' % n_clusters_)
    cluster_dict = {i: mem_locs[db.labels_ == i] for i in xrange(n_clusters_)}
    for n, cluster in cluster_dict.items():
        locs = set([x[0] for x in cluster.tolist()])
        logger.debug("Addresses in Cluster %d: %s" % (n, repr([hex(x) for x in
                                                          locs])))
    # Um, scikit, this is not how you organize data.
    clusters = {}
    for k, v in cluster_dict.items():
        s = v.tolist()
        t = [u[0] for u in s]
        clusters[k] = set(t)
    return clusters


if __name__ == '__main__':
    data = np.genfromtxt(sys.argv[1], dtype=None)
    clusters = cluster_peripherals(data)
    import IPython;

    IPython.embed()
