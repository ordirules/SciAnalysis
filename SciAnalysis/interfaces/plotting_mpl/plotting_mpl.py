import matplotlib.pyplot as plt
import SciAnalysis.config as config
import os.path

import numpy as np

_ROOTDIR = config.resultsroot
_ROOTMAP = config.resultsrootmap


# store results decorator for plotting library
# as of now function that returns decorator takes no arguments

# TODO move to general tools
def make_dir(directory):
    ''' Creates directory if doesn't exist.'''
    if not os.path.isdir(directory):
        os.makedirs( directory )


def _cleanup_str(string):
    string = string.replace(" ", "_")
    string = string.replace("/", "_")
    string = string.replace("(", "_")
    string = string.replace(")", "_")
    string = string.replace(":", "_")
    return string

def _make_fname_from_attrs(attrs):
    ''' make filename from attributes.
        This will likely be copied among a few interfaces.
    '''
    if 'experiment_alias_directory' not in attrs:
        raise ValueError("Error cannot find experiment_alias_directory in attributes. Not saving.")

    # remove the trailing slash
    rootdir = attrs['experiment_alias_directory'].strip("/")

    if _ROOTMAP is not None:
        rootdir = rootdir.replace(_ROOTMAP[0], _ROOTMAP[1])
    elif _ROOTDIR is not None:
        rootdir = _ROOTDIR

    if 'detector_name' not in attrs:
        raise ValueError("Error cannot find detector_name in attributes")
    else:
        detector_name = _cleanup_str(attrs['detector_name'])

    if 'sample_savename' not in attrs:
        raise ValueError("Error cannot find sample_savename in attributes")
    else:
        sample_savename = _cleanup_str(attrs['sample_savename'])

    if 'stream_name' not in attrs:
        #raise ValueError("Error cannot find stream_name in attributes")
        stream_name = 'unnamed_analysis'
    else:
        stream_name = _cleanup_str(attrs['stream_name'])

    if 'scan_id' not in attrs:
        raise ValueError("Error cannot find scan_id in attributes")
    else:
        scan_id = _cleanup_str(str(attrs['scan_id']))

    outdir = rootdir + "/" + "/" + detector_name + "/" + stream_name + "/plots"
    make_dir(outdir)
    outfile = outdir + "/" + sample_savename + "_" + scan_id

    return outfile


def store_results(results, **plot_opts):
    ''' Store the results to a numpy file.
        This saves to numpy format by default.
        May raise an error if it doesn't understand data.
        Expects a StreamDoc

        For images, you'll need to use a plotting/image interface (not implemented yet).

        plot_opts : plot options forwarded to matplotlib
            file_format : the file format
            images : keys of images
            lines : keys of lines to plot (on top of images)
                if element is a tuple, assume (x,y) format, else assume it's just y
            labelsize
            xlabel
            ylabel
            title
    '''
    # TODO : move some of the plotting into a general object
    if 'file_format' in plot_opts:
        file_format = plot_opts['file_format']
    else:
        file_format = "jpg"

    if 'plot_kws' in plot_opts:
        plot_kws = plot_kws

    data = results['kwargs']

    if 'attributes' not in results:
        raise ValueError("attributes not in the sciresults. (Is this a valid SciResult object?)")
    attrs = results['attributes']

    outfile = _make_fname_from_attrs(attrs) + ".png"
    print("writing to {}".format(outfile))

    if 'images' in plot_opts:
        images = plot_opts['images']
    else:
        images = []
    if 'lines' in plot_opts:
        lines = plot_opts['lines']
    else:
        lines = []

    xlims = None
    ylims = None
    plt.ioff()
    fig = plt.figure(figsize=(10,10))
    plt.clf()
    ax = plt.subplot()
    for key in images:
        # find some reasonable color scale
        image = data[key]
        vmin, vmax = findLowHigh(image)
        if 'vmin' in plot_opts:
            vmin = plot_opts['vmin']
        if 'vmax' in plot_opts:
            vmax = plot_opts['vmax']
        if image.ndim == 2:
            if isinstance(image, np.ndarray):
                plt.imshow(image,vmin=vmin, vmax=vmax)
                plt.colorbar()
        elif image.ndim == 3:
            nimgs = image.shape[0]
            dim = int(np.ceil(np.sqrt(nimgs)))
            fig, axes = plt.subplots(dim,dim)
            axes = np.array(axes).ravel()
            for j in range(len(image)):
                if isinstance(image, np.ndarray):
                    axes[j].imshow(image[j])
    for line in lines:
        if isinstance(line, tuple) and len(line) == 2:
            x = data[line[0]]
            y = data[line[1]]
        else:
            x = np.arange(len(y))
            y = line
        plt.plot(x,y)
        if xlims is None:
            xlims = [np.min(x), np.max(x)]
        else:
            xlims[0] = np.min([np.min(x), xlims[0]])
            xlims[1] = np.max([np.max(x), xlims[1]])
        if ylims is None:
            ylims = [np.min(y), np.max(y)]
        else:
            ylims[0] = np.min([np.min(y), ylims[0]])
            ylims[1] = np.max([np.max(y), ylims[1]])
    if xlims is not None:
        plt.xlim(xlims[0], xlims[1])
    if ylims is not None:
        plt.ylim(ylims[0], ylims[1])

    # plotting the extra options
    if 'labelsize' in plot_opts:
        labelsize=plot_opts['labelsize']
    else:
        labelsize=20

    if 'hideaxes' in plot_opts:
        hideaxes = plot_opts['hideaxes']
    else:
        hideaxes = False

    if 'xlabel' in plot_opts:
        xlabel = plot_opts['xlabel']
        plt.xlabel(xlabel, size=labelsize)

    if 'ylabel' in plot_opts:
        ylabel = plot_opts['ylabel']
        plt.xlabel(xlabel, size=labelsize)
        plt.ylabel(ylabel, size=labelsize)

    if 'title' in plot_opts:
        title = plot_opts['title']
        plt.title(title)
    if 'scale' in plot_opts:
        scale = plot_opts['scale']
        if scale is 'loglog':
            ax.set_xscale('log')
            ax.set_yscale('log')
        elif scale is 'semilogx':
            ax.set_xscale('log')
        elif scale is 'semilogy':
            ax.set_yscale('log')
        # else ignore

    if hideaxes:
        ax.get_xaxis().set_visible(False)
        ax.get_yaxis().set_visible(False)



    # save
    fig.savefig(outfile)
    # make sure no mem leaks, just close
    plt.close(fig)

    # now do the plotting

def findLowHigh(img, maxcts=None):
    ''' Find the reasonable low and high values of an image
            based on its histogram.
            Ignore the zeros
    '''
    if maxcts is None:
        maxcts = 65536
    w = np.where((~np.isnan(img.ravel()))*(~np.isinf(img.ravel())))
    hh,bb = np.histogram(img.ravel()[w], bins=maxcts, range=(1,maxcts))
    hhs = np.cumsum(hh)
    hhsum = np.sum(hh)
    if hhsum > 0:
        hhs = hhs/np.sum(hh)
        wlow = np.where(hhs > .01)[0] #5%
        whigh = np.where(hhs < .99)[0] #95%
    else:
        # some arbitrary values
        wlow = np.array([1])
        whigh = np.array([10])

    if len(wlow):
        low = wlow[0]
    else:
        low = 0
    if len(whigh):
        high = whigh[-1]
    else:
        high = maxcts
    if high <= low:
        high = low + 1
    # debugging
    #print("low: {}, high : {}".format(low, high))
    return low, high
