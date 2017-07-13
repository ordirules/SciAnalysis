#!/usr/bin/env python
import numpy as np

# from distutils.core import setup
import setuptools

setuptools.setup(name='SciAnalysis',
                 version='1.0',
                 author='Kevin Yager',
                 description="CMS Analysis",
                 include_dirs=[np.get_include()],
                 author_email='lhermitte@bnl.gov',
                 # install_requires=['six', 'numpy'],  # essential deps only
                 keywords='CMS X-ray Analysis',
                 )
