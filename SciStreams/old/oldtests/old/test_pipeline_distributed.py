# same as test_pipeline but distributed
import tempfile
from PIL import Image
import os
import numpy as np

import time

from SciAnalysis.databases import databases
from detectors import detectors2D

from dask import delayed
from dask.delayed import Delayed

from cache import cache

from toolz import curry

from databroker.broker import Header
from distributed import Client
_pipeline_client = Client("10.11.128.3:8786")

# testing
from nose.tools import assert_true, assert_false
from numpy.testing import assert_array_almost_equal

from SciAnalysis.SciResult import SciResult
from SciAnalysis.decorators import parse_sciresults

# base class
class Protocol:
    pass

# TODO : add run_default
# TODO : add run_explicit
# TODO : how to handle implicit arguments? (Some global maybe?)
# TODO : add databroker keymap

'''
For now, assume all incoming arguments are well defined each step.

There will be a case where this is not true.
For ex : linecut -> need to backpropagate until the latest data set that
is computed is found. It will be necessary to figure out what to fill in
for missing arguments for that data set.

Ideas introduced:
1. SciResult : this is a dictionary of results. It may contain data
    stored in filestore. 
2. new class specifiers : 
    _name : some unique name for protocol
    _depends : dependencies of the arguments of the protocol
        {'_arg0' : ..., '_arg1' : ..., ... 'foo' : ...}
        _argn means nth argument, rest are keywords
    _func_args : the explicit arguments for function
    _keymap : the keymap of results
3. two step run process:
    result = myclass(**kwargs).run(**moreoverridingargs).compute()
'''

#

    
class lookup:
    _accepted_args = ['infile']
    _keymap = {'infile' : 'infile'}
    _output_names = ['image']
    _name = "XS:load_saxs_image"

    def __init__(self, **kwargs):
        self.kwargs= kwargs

    def run(self, **kwargs):
        new_kwargs = dict()
        new_kwargs.update(self.kwargs.copy())
        new_kwargs.update(kwargs)
        return self.run_explicit(_name=self._name, **new_kwargs)

    # need **kwargs to allow extra args to be passed
    @delayed(pure=False)
    @parse_sciresults(_keymap, _output_names)
    def run_explicit(database=None, protocol_name=None, sample=None, **kwargs):
        # Need to import inside for distributed
        from SciAnalysis.databases import databases
        if isinstance(header, Header):
            uid = header['start']['uid']
        elif not isinstance(header, str):
            raise ValueError("Sorry, is not a string or header")
        # find the latest analysis run of the sample using protocol_name

        return None
    
class load_saxs_image:
    _accepted_args = ['infile']
    _keymap = {'infile' : 'infile'}
    _output_names = ['image']
    _name = "XS:load_saxs_image"

    def __init__(self, **kwargs):
        self.kwargs= kwargs

    def run(self, **kwargs):
        new_kwargs = dict()
        new_kwargs.update(self.kwargs.copy())
        new_kwargs.update(kwargs)
        return self.run_explicit(_name=self._name, **new_kwargs)

    # need **kwargs to allow extra args to be passed
    @delayed(pure=False)
    @parse_sciresults(_keymap, _output_names)
    def run_explicit(infile = None, **kwargs):
        # Need to import inside for distributed
        from SciAnalysis.databases import databases
        if isinstance(infile, Header):
            if 'detector' not in kwargs:
                raise ValueError("Sorry, detector must be passed if supplying a header")
            if 'database' not in kwargs:
                raise ValueError("Sorry, database must be passed if supplying a header")
            detector = kwargs.pop('detector')
            database = kwargs.pop('database')
            database = databases[database]['data']
            img = database.get_images(infile, detector['image_key']['value'])[0]
            img = np.array(img)
        elif isinstance(infile, np.ndarray):
            img = infile
        elif isinstance(infile, str):
            img = np.array(Image.open(infile))
        else:
            raise ValueError("Sorry, did not understand the input argument: {}".format(infile))

        return img

class load_calibration:
    # TODO: reevaluate if _accepted_args necessary
    _accepted_args = ['calibration']
    _keymap = {'calibration' : 'calibration'}
    _output_names = ['calibration']
    _name = "XS:calibration"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, **kwargs):
        new_kwargs = dict()
        new_kwargs.update(self.kwargs.copy())
        new_kwargs.update(kwargs)
        return self.run_explicit(_name=self._name, **new_kwargs)

    def add(self, name=None, value=None, unit=None):
        self.kwargs.update({name : {'value' : value, 'unit' : unit}})

    @delayed(pure=True)
    @parse_sciresults(_keymap, _output_names)
    def run_explicit(calibration={}, **kwargs):
        '''
            Load calibration data.
            The data must be a dictionary.
            either:
                load_calibration(calibration=myCalib)
            or:
                load_calibration(wavelength=fdsa) etc
            
            It is curried so you can keep overriding parameters.
    
    
            This is area detector specific.
        '''
        # defaults of function
        _defaults= {'wavelength' : {'value' : None, 'unit' : 'Angstrom'},
                     'beamx0' : {'value' : None, 'unit' : 'pixel'},
                     'beamy0' : {'value' : None, 'unit' : 'pixel'},
                     'sample_det_distance' : {'value' : None, 'unit' : 'm'},
                    # Area detector specific entries:
                     # width is columns, height is rows
                     'AD_width' : {'value' : None, 'unit' : 'pixel'},
                     'AD_height' : {'value' : None, 'unit' : 'pixel'},
                     'pixel_size_x' : {'value' : None, 'unit' : 'pixel'},
                     'pixel_size_y' : {'value' : None, 'unit' : 'pixel'},
                       #TODO : This assumes data has this detector, not good to use, remove eventually
                     'detectors' : {'value' : ['pilatus300'], 'unit' : None},
    
                    }
    
        if isinstance(calibration, Header):
            # a map from Header start doc to data
            # TODO : move out of function
            calib_keymap = {'wavelength' : {'key' : 'calibration_wavelength_A',
                                            'unit' : 'Angstrom'},
                            'detectors' : {'key' : 'detectors',
                                            'unit' : 'N/A'},
                            'beamx0' : {'key' : 'detector_SAXS_x0_pix', 
                                        'unit' : 'pixel'},
                            'beamy0' : {'key' : 'detector_SAXS_y0_pix',
                                        'unit' : 'pixel'},
                            'sample_det_distance' : {'key' : 'detector_SAXS_distance_m',
                                                     'unit' : 'pixel'}
                            }
    
            start_doc = calibration['start']
            calib_tmp = dict()
            # walk through defaults
            for key, entry in calib_keymap.items():
                start_key = entry['key'] # get name of key
                unit = entry['unit']
                val = start_doc.get(start_key, _defaults[key]['value'])
                calib_tmp[key] = {'value' : val,
                                  'unit' : unit}
    
            # finally, get the width and height by looking at first detector in header
            # TODO : add ability to read more than one detector, maybe in calib_keymap
            first_detector = start_doc[calib_keymap['detectors']['key']][0]
            detector_key = detectors2D[first_detector]['image_key']['value']
    
            # look up in local library
            pixel_size_x = detectors2D[first_detector]['pixel_size_x']['value']
            pixel_size_x_unit = detectors2D[first_detector]['pixel_size_x']['unit']
            pixel_size_y = detectors2D[first_detector]['pixel_size_y']['value']
            pixel_size_y_unit = detectors2D[first_detector]['pixel_size_y']['unit']
    
            img_shape = detectors2D[first_detector]['shape']
    
            calib_tmp['pixel_size_x'] = dict(value=pixel_size_x, unit=pixel_size_x_unit)
            calib_tmp['pixel_size_y'] = dict(value=pixel_size_y, unit=pixel_size_y_unit)
            calib_tmp['shape'] = img_shape.copy() #WARNING : copies only first level, this is one level dict
            calibration = calib_tmp
        
        # update calibration with all keyword arguments
        for key, val in kwargs.items():
            # make sure not a hidden parameter
            if not key.startswith("_") and key not in calibration:
                calibration[key] = _defaults[key]
        # now override with kwargs
        for key in _defaults.keys():
            if key in kwargs:
                calibration[key] = kwargs[key]
    
        return calibration
        

class circular_average:
    _accepted_args = ['calib']
    _keymap = {'calibration': 'calibration', 'image' : 'image'}
    _output_names = ['sqx', 'sqy']
    _name = "XS:circular_average"

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def run(self, **kwargs):
        new_kwargs = dict()
        new_kwargs.update(self.kwargs.copy())
        new_kwargs.update(kwargs)
        return self.run_explicit(_name=self._name, **new_kwargs)

    @delayed(pure=True)
    @parse_sciresults(_keymap, _output_names)
    def run_explicit(image=None, calibration=None, bins=100, mask=None, **kwargs):
        #print(calibration)
        #print("computing")
        x0, y0 = calibration['beamx0']['value'], calibration['beamy0']['value']
        from skbeam.core.accumulators.binned_statistic import RadialBinnedStatistic
        img_shape = calibration['shape']['value']
        #print(img_shape)
        rbinstat = RadialBinnedStatistic(img_shape, bins=bins, origin=(y0,x0), mask=mask)
        sq = rbinstat(image)
        sqx = rbinstat.bin_centers
        return sqx, sq


    


    
# Completed tests (above are WIP)
#
def test_sciresult_parser():
    ''' This test ensures taht 
        The inputs and outputs of functions are properly 
            normalized using SciResult.

        The inputs can be SciResults or explicit arguments
        and the output is a sciresult with only one entry
            with name _output_name
    '''
    @parse_sciresults({'a' : 'a'}, 'a')
    def foo(a=1, **kwargs):
        return a

    test = SciResult(a=1)

    res = foo(a=test)
    assert res['a'] == 1


def test_sciresult():
    ''' Just ensure instance checking is fine for SciResult.'''
    # necessary when trying to distinguish SciResult from dict
    assert_true(isinstance(SciResult(), dict))
    assert_false(isinstance(dict(), SciResult))


# this will be False, so don't do, an issue with dask
def test_delayed_passthrough():
    ''' Test that a class that inherits dict isn't improperly interpreted and
        modified.
        This is from Issue https://github.com/dask/dask/issues/2107
    '''
    class MyClass(dict):
        pass

    @delayed(pure=True)
    def foo(arg):
        assert_true(isinstance(arg, MyClass))

    res = foo(MyClass())
    res.compute()

def test_calibration():
    # TODO : Replace with a portable db to to the db testing
    cmsdb = databases['cms']['data']
    # I randomly chose some header
    header = cmsdb['89e8caf6-8059-43ff-9a9e-4bf461ee95b5']
    calibres = load_calibration(calibration=header).run()
    assert isinstance(calibres, Delayed)
    calibres = calibres.compute()
    assert isinstance(calibres, SciResult)
    #print(calibres)

    calibres = load_calibration()
    calibres.add(name='beamx0', value=50, unit='pixel')
    calibres.add(name='beamy0', value=50, unit='pixel')
    calibres.run().compute()
    #print(calibres)
    
def test_load_saxs_img(plot=False):
    ''' test the load_saxs_img class'''
    cmsdb = databases['cms']['data']
    # I randomly chose some header
    header = cmsdb['89e8caf6-8059-43ff-9a9e-4bf461ee95b5']

    tmpdir_data = tempfile.TemporaryDirectory().name
    os.mkdir(tmpdir_data)

    # make dummy data
    img_shape = (100,100)
    data = np.ones(img_shape, dtype=np.uint8)
    data[50:60] = 0
    data_filename = tmpdir_data + "/test_data.png"
    im = Image.fromarray(data)
    im.save(data_filename)

    # testing that protocol can take a SciResult or data
    # test with data
    res_fileinput = load_saxs_image(infile=data_filename).run()
    # test with sciresult
    head = SciResult(infile=data_filename)
    res_sciresinput = load_saxs_image(infile=head).run()

    res_headerinput = load_saxs_image(infile=header, detector=detectors2D['pilatus300'], database='cms').run()

    assert_true(isinstance(res_sciresinput, Delayed))
    assert_true(isinstance(res_fileinput, Delayed))
    assert_true(isinstance(res_headerinput, Delayed))

    # test with data
    res_fileinput = res_fileinput.compute()
    # test with sciresult
    res_sciresinput = res_sciresinput.compute()
    res_headerinput = res_headerinput.compute()

    assert_array_almost_equal(data, res_fileinput['image'])
    assert_array_almost_equal(data, res_sciresinput['image'])

    if plot:
        import matplotlib.pyplot as plt
        plt.ion()
        plt.figure(0);plt.clf()
        plt.imshow(res_headerinput['image'])

def test_circular_average(plot=False, output=False):
    cmsdb = databases['cms']['data']
    # I randomly chose some header
    header = cmsdb['89e8caf6-8059-43ff-9a9e-4bf461ee95b5']


    # make dummy data
    tmpdir_data = tempfile.TemporaryDirectory().name
    os.mkdir(tmpdir_data)
    img_shape = (100,100)
    data = np.ones(img_shape, dtype=np.uint8)
    data[50:60] = 0
    data_filename = tmpdir_data + "/test_data.png"
    im = Image.fromarray(data)
    im.save(data_filename)


    calibres = load_calibration(calibration=header).run().compute()
    image = load_saxs_image(infile=header, detector=detectors2D['pilatus300'], database='cms').run().compute()
    ##image = load_saxs_image(infile=data_filename).run().compute()
    sq = circular_average(image=image, calibration=calibres).run().compute()
    #sq = circular_average(image=image, calibration=calibres).run().compute()

    #if plot:
        #import matplotlib.pyplot as plt
        #plt.ion()
        #plt.figure(0);plt.clf()
        #plt.loglog(sq['sqx'], sq['sqy'])

    if output:
        return calibres

