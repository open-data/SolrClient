import datetime
import logging
import sys
import os
import gzip
import shutil
import random
import json

class IndexQ():
    '''
    IndexQ sub module will help with indexing large amounts of content into Solr. It can be used to de-couple data processing with indexing. 
    
    For example, if you are working through a bunch of data that generates many small records that need to be updated you will need to either send them to Solr one at a time, or buffer them somewhere and possible combine multiple items into a larger update for solr. This is what this submodule is supposed to do for you. It uses an internal queue to buffer items and write them to the file system at certain increments. Then the indexer component can pick up these items and index them to Solr as a separate process. 
    
    Each queue is set up with the following directory structure
    queue_name/ 
     - todo/
     - done/ 
    
    Items get saved to the todo directory and once an item is processed it gets moved to the done directory. Items are also processed in chronological order. 
    '''

    def __init__(self, basepath, queue, compress=False, size=0, devel=False, threshold = 0.90,  mode='in', **kwargs ):
        '''
        :param string basepath: Path to the root of the indexQ. All other queues will get created underneath this. 
        :param string queue: Name of the queue. 
        :param string mode: If you are queuing (in) or de-queuing (out)
        :param bool compress: If todo files should be compressed, set to True if there is going to be a lot of data and these files will be sitting there for a while.
        :param int size: Internal buffer size (MB) that queued data must be to get written to the file system. If not passed, the data will be written to the filesystem as it is sent to IndexQ, otherwise they will be written when the buffer reaches 90%. 
        
        Example Usage::
            i = IndexQ('/data/indexq','parsed_data')
            
        '''
        self.logger = logging.getLogger(__package__)
        
        self._basepath = basepath
        self._queue_name = queue
        self._compress = compress
        self._size = size
        self._devel = devel
        self._threshold = threshold
        self._qpathdir = os.path.join(self._basepath,self._queue_name)
        self._todo_dir = os.path.join(self._basepath,self._queue_name,'todo')
        self._done_dir = os.path.join(self._basepath,self._queue_name,'done')
        self._mode = mode
        self._locked = False
        
        #Lock File        
        self._lck = os.path.join(self._qpathdir,'index.lock')
        
        for dir in [self._qpathdir, self._todo_dir, self._done_dir]:
            if not os.path.isdir(dir):
                os.makedirs(dir)
        
        if self._mode == 'in':
            #First argument will be datestamp, second is counter
            self._output_filename_pattern = self._queue_name+"_{}.json"
            self._preprocess = self._buffer(self._size*1000000, self._write_file)
            
            
        self.logger.info("Opening Queue {}".format(queue))
    
    #This part is all about loading data
    def _gen_file_name(self):
        '''
        Generates a random file name based on self._output_filename_pattern for the output to do file. 
        '''
        date = datetime.datetime.now()
        dt = "{}-{}-{}-{}-{}-{}-{}".format(str(date.year),str(date.month),str(date.day),str(date.hour),str(date.minute),str(date.second),str(random.randint(0,10000)))
        return self._output_filename_pattern.format(dt) 
            
    def add(self, item = None, finalize = False):
        '''
        Takes a string, dictionary or list of items for adding to queue. To help troubleshoot it will output the updated buffer size, however when the content gets written it will output the file path of the new file. Generally this can be safely discarded. 
        
        :param <dict,list> item: Item to add to the queue. If dict will be converted directly to a list and then to json. List must be a list of dictionaries. If a string is submitted, it will be written out as-is immediately and not buffered. 
        '''
        if item:
            if type(item) is list:
                if self._devel: self.logger.debug("Adding List")
                check = list(set([type(d) for d in item]))
                if len(check) > 1 or dict not in check:
                    raise ValueError("More than one data type detected in item (list). Make sure they are all dicts of data going to Solr")
            elif type(item) is dict:
                if self._devel: self.logger.debug("Adding Dict")
                item = [item]
            elif type(item) is str:
                if self._devel: self.logger.debug("Adding String")
                return self._write_file(item)
            else:
                raise ValueError("Not the right data submitted. Make sure you are sending a dict or list of dicts")
        return self._preprocess(item,finalize)

    def _write_file(self,content):
        while True:
            path = os.path.join(self._todo_dir,self._gen_file_name())
            if self._compress:
                path += '.gz'
            if not os.path.isfile(path):
                break
        self.logger.info("Writing new file to {}".format(path))
        if self._compress:
            with gzip.open(path, 'wb') as f:
                f.write(content.encode('utf-8'))
        else:
            with open(path,'w') as f:
                f.write(content)
        return path

        
    def _buffer(self,size,callback):
        _c = {
            'size': 0,
            'callback': callback,
            'osize': size if size > 0 else 1,
            'buf': []
        }
        self.logger.debug("Starting Buffering Queue with Size of {}".format(size))
        def inner(item = None,finalize = False):
            if item:
                #Buffer Item
                [_c['buf'].append(x) for x in item]
                #Wish I didn't have to make a string of it over here sys.getsizeof wasn't providing accurate info either.
                _c['size'] += len(str(item))
                if self._devel:
                    self.logger.debug("Item added to Buffer {} New Buffer Size is {}".format(self._queue_name, _c['size']))
            if _c['size'] / _c['osize'] > self._threshold or (finalize is True and len(_c['buf']) >= 1):
                #Write out the buffer
                if self._devel:
                    if finalize:
                        self.logger.debug("Finalize is True, writing out")
                    else:
                        self.logger.debug("Buffer Filled, writing out")
                res = _c['callback'](json.dumps(_c['buf'], indent=0, sort_keys=True))
                if res:
                    _c['buf'] = []
                    _c['size'] = 0
                    return res
                else:
                    raise RuntimeError("Couldn't write out the buffer." + _c)
            return _c['size']
        return inner

    #This is about pullind data out
    def _lock(self):
        '''
        Locks, or returns False if already locked
        '''
        if not self._is_locked():
            with open(self._lck,'w') as fh:
                if self._devel: self.logger.debug("Locking")
                fh.write(str(os.getpid()))
            return True
        else:
            return False
    
    def _is_locked(self):
        if os.path.isfile(self._lck):
            try:
                import psutil
            except ImportError:
                self.logger.error("Index already locked")
                return True #Lock file exists and no psutil
            #If psutil is imported
            with open(self._lck) as f:
                pid = f.read()
            return True if psutil.pid_exists(int(pid)) else False
        else:
            return False
        
    def _unlock(self):
        if self._devel: self.logger.debug("Unlocking Index")
        if self._is_locked():
            os.remove(self._lck)
            return True
        else:
            return True
        
    def get_all_as_list(self,dir='_todo_dir'):
        '''
        Returns a list of the the full path to all items currently in the todo directory. The items will be listed in ascending order based on filesystem time. 
        This will re-scan the directory on each execution. 
        
        Do not use this to process items, this method should only be used for troubleshooting or something axillary. To process items use get_todo_items() iterator. 
        '''
        dir = getattr(self,dir)
        list = [x for x in os.listdir(dir) if x.endswith('.json') or x.endswith('.json.gz')]
        full = [os.path.join(dir,x) for x in list]
        full.sort(key=lambda x: os.path.getmtime(x))
        return full
        

       
    def get_todo_items(self,**kwargs):
        '''
        Returns an iterator that will provide each item in the todo queue. Note that to complete each item you have to run complete method with the output of this iterator. 
        '''
        def inner(self):
            yield from self.get_all_as_list()
            self._unlock()
            
        if not self._is_locked():
            if self._lock():
                return inner(self)
        raise RuntimeError("Index Already Locked")
    
    def complete(self,filepath,compress=True):
        '''
        Marks the item as complete by moving it to the done directory and optionally gzipping it. 
        '''
        
        if self._mode == 'in':
            raise RuntimeError("The mode for this IndexQ instance is input, it needs to be output for this to work")
        elif self._mode == 'out':
            if not os.path.exists(filepath):
                raise("Can't Complete {}, it doesn't exist".format(filepath))
            if self._devel: self.logger.debug("Completing {} ".format(filepath))
            try:
                shutil.move(
                    filepath,
                    os.path.join(self._done_dir,os.path.split(filepath)[-1]))
                self.logger.info("{} Completed".format(filepath))
            except:
                self.logger.error("Couldn't Complete {}".format(filepath))
                raise
                

    def index(self, solr, collection, procs=1, method='stream_file', **kwargs):
        '''
        Will index the queue into a specified solr instance and collection. Specify multiple procs to make this faster. 
        Used to automatically index the todo file into Solr. 
        :param object solr: SolrClient object
        :param string collection: The name of the collection to index document into. 
        :param int procs: Number of simultaneous processes to spin up for indexing. 
        '''
        method = getattr(solr,method)
        if procs == 1:
            for todo_file in self.get_todo_items():
                solr.method(todo_file)
                
            