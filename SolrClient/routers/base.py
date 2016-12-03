import random


class BaseRouter(object):
    def __init__(self, solr, hosts):
        self.solr = solr
        self.hosts = self._proc_host(hosts)

    def get_hosts(self, **kwargs):
        raise NotImplementedError

    def _proc_host(self, host):
        if type(host) is str:
            return [host]
        elif type(host) is list:
            return host
        raise Exception("host:%s type: %s is not string or list of strings" % (host, type(host)))

    def shuffle_hosts(self):
        """
        Shuffle hosts so we don't always query the first one.
        Example: using in a webapp with X processes in Y servers, the hosts contacted will be more random.
        The user can also call this function to reshuffle every 'x' seconds or before every request.
        :return:
        """
        if len(self.hosts) > 1:
            random.shuffle(self.hosts)
        return self.hosts
