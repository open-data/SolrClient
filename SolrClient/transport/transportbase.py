import logging
from ..exceptions import *


    
class TransportBase:
    """
    Base Transport Class
    """
    def __init__(self,solr,host=None,auth=[None,None]):
        
        self.solr = solr
        self.devel = True if self.solr.devel else False
        self.logger=logging.getLogger(str(__package__))
        self.HOST_CONNECTIONS = self._proc_host(host)
        self.auth = auth
        #Initialize transport specific config
        self.setup()
        
        
    def _proc_host(self,host):
        if type(host) is str:
            return [host]
        elif type(host) is list:
            return host
            
    def _retry(function):
        '''
        Internal mechanism to try to send data to multiple Solr Hosts if the query fails on the first one. 
        '''
        def inner(self,**kwargs):
            for host in self.HOST_CONNECTIONS:
                try:
                    data =  function(self,host,**kwargs)
                    return data
                except SolrError as e:
                    self.logger.exception(e)
                    raise
                except ConnectionError as e:
                    self.logger.error("Tried connecting to Solr, but couldn't because of the following exception.")
                    self.logger.exception(e)
                    if '401' in e.__str__():
                        raise
        return inner
        
    @_retry
    def send_request(self, host, **kwargs):
        res_dict = self._send(host, **kwargs)
        if 'errors' in res_dict:
            error = ", ".join([x for x in res_dict['errors'][0]['errorMessages']])
            raise SolrError(error)
        elif 'error' in res_dict:
            raise SolrError(str(res_dict['error']))
        return res_dict
        