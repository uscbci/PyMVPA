# emacs: -*- coding: utf-8; mode: python; py-indent-offset: 4; indent-tabs-mode: nil -*-
# vi: set ft=python sts=4 ts=4 sw=4 et:
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the PyMVPA package for the
#   copyright and license terms.
#
#   The initial version of the code was contributed by Ingo Fründ and is
#   Coypright (c) 2008 by Ingo Fründ ingo.fruend@googlemail.com
#
### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Plot flat maps of cortical surfaces.

WiP"""

__docformat__ = 'restructuredtext'

import numpy as np
from mvpa2.support.nibabel import surf, afni_suma_1d
from mvpa2.datasets.base import Dataset
import re

from mvpa2.base import externals

if externals.exists("matplotlib", raise_=True):
    import matplotlib.pyplot as plt

if externals.exists("griddata", raise_=True):
    from mvpa2.support.griddata import griddata

from mvpa2.support.nibabel.surf import vector_alignment_find_rotation

# older versions of Numpy do not support nanmin/nanmax, so provide that here
def _get_nan_vector_operator(func):
    def f(xs):
        if not len(xs.shape) == 1:
            raise ValueError('Only vector input is supported')
        msk = np.logical_not(np.isnan(xs))
        return func(xs[msk])

    return f



nanmin_wrapper = _get_nan_vector_operator(np.min)
nanmax_wrapper = _get_nan_vector_operator(np.max)



def unstructured_xy2grid_xy_vectors(x, y, min_nsteps):
    '''From unstructured x and y values, return lists of x and y coordinates
    to form a grid
    
    Parameters
    ----------
    x: np.ndarray
        x coordinates
    y: np.ndarray
        y coordinates
    min_nsteps: int
        minimal length of output
        
    Returns
    -------
    (xi, yi): tuple of np.ndarray
        xi contains values ranging from (approximately) min(x) to max(x);
        yi is similar. min(len(xi),len(yi))=min_steps.
    '''
    if len(x) != len(y):
        raise ValueError('Shape mismatch')

    xmin, ymin = np.min(x), np.min(y)
    xmax, ymax = np.max(x), np.max(y)

    xran, yran = xmax - xmin, ymax - ymin
    delta = min(xran, yran) / (min_nsteps - 1)
    xsteps = 1 + np.ceil(xran / delta)
    ysteps = 1 + np.ceil(yran / delta)

    # x and y values on the grid
    xi = (np.arange(xsteps) + .5) * delta + xmin
    yi = (np.arange(ysteps) + .5) * delta + ymin

    return xi, yi



def flat_surface2xy(surface, max_deformation):
    '''Returns a tuple with x and y coordinates of a flat surface
    
    Parameters
    ----------
    surface: Surface
        flat surface
    max_deformation: float
        maximum deformation to make a non-flat surface flat.
        The normals of each face must have a dot product with the average
        face normal that is not less than (1-max_deformation); otherwise
        an exception is raised. The rationale for this option is that certain
        surfaces may be almost flat, and those can be made flat without
        problem; but surfaces that are not flat, such as inflated surfaces,
        should not be flattable.
    
    Returns
    -------
    x: np.ndarray
        x coordinates
    y: np.ndarray
        y coordinates
    
    Notes
    -----
    If the surface is not flat (any z coordinate is non-zero), an exception
    is raised.
    '''

    s = surf.from_any(surface)
    face_normals = s.face_normals

    msk = np.all(np.logical_not(np.isnan(face_normals)), 1)

    avg_face_normal = s.nanmean_face_normal
    deformations = abs(
        1 - abs(np.dot(avg_face_normal[np.newaxis], face_normals[msk].T)))
    too_deformed = np.nonzero(deformations > max_deformation)[0]
    if len(too_deformed) > 0:
        raise ValueError('Surface is not sufficiently flat with '
                         'max_deformation=%.3f' % max_deformation)

    # find rotation so that surface is more or less orthogonal to
    # the unit vector (0,0,1)
    v = s.vertices
    z_axis = np.asarray([0, 0, 1.])
    r = vector_alignment_find_rotation(avg_face_normal, z_axis)

    # apply rotation
    v_rotated = r.dot(v.T)

    # discard z-coordinate
    x = v_rotated[0]
    y = v_rotated[1]

    return x, y



def flat_surface2grid_mask(surface, min_nsteps, max_deformation):
    '''Computes a mask and corresponding coordinates from a flat surface 
    
    Parameters
    ----------
    surface: Surface
        flat surface
    min_nsteps: int
        minimum number of pixels in x and y direction
    max_deformation: float
        maximum deformation to make a non-flat surface flat.
        The normals of each face must have a dot product with the average
        face normal that is not less than (1-max_deformation); otherwise
        an exception is raised. The rationale for this option is that
        certain surfaces may be almost flat, and projecting the vertices
        on a truly flat surface should be fine. On the other hand, surfaces
        that are definitly not flat (such as full cortical surface models)
        should cause an error to be raised when it is attempted to flatten
        them
        
    Returns
    -------
    x: np.ndarray
        x coordinates of surface
    y: np.ndarray
        y coordinates of surface
    m: np.ndarray
        mask array of size PxQ, with min(P,Q)==min_nsteps.
        m[i,j]==True iff the position at (i,j) is 'inside' the flat surface
    xi: np.ndarray
        vector of length Q with interpolated x coordinates
    yi: np.ndarray
        vector of length P with interpolated y coordinates
    
    Notes
    -----
    The output of this function can be used with scipy.interpolate.griddata
    '''

    surface = surf.from_any(surface)
    x, y = flat_surface2xy(surface, max_deformation)
    xmin = np.min(x)

    xi, yi = unstructured_xy2grid_xy_vectors(x, y, min_nsteps)
    delta = xi[1] - xi[0]
    vi2xi = (x - xmin) / delta

    # compute paths of nodes on the border
    pths = surface.nodes_on_border_paths()

    # map x index to segments that cross the x coordinate
    # (a segment is a pair (i,j) where nodes i and j share a triangle
    #  and are on the border)
    xidx2segments = dict()

    for pth in pths:
        # make a tour across pairs (i,j)
        j = pth[-1]
        for i in pth:
            pq = vi2xi[i], vi2xi[j]
            p, q = min(pq), max(pq)
            # always go left (p) to right (q)
            for pqs in np.arange(np.ceil(p), np.ceil(q)):
                # take each point in between
                ipqs = int(pqs)

                # add to xidx2segments
                if not ipqs in xidx2segments:
                    xidx2segments[ipqs] = list()
                xidx2segments[ipqs].append((i, j))

            # take end point from last iteration as starting point
            # in next iteration
            j = i


    # space for the mask
    yxshape = len(yi), len(xi)
    msk = np.zeros(yxshape, dtype=np.bool_)

    # see which nodes are *inside* a surface 
    # (there can be multiple surfaces)
    for ii, xpos in enumerate(xi):
        if not ii in xidx2segments:
            continue
        segments = xidx2segments[ii]
        for jj, ypos in enumerate(yi):
            # based on PNPOLY (W Randoph Franklin)
            # http://www.ecse.rpi.edu/~wrf/Research/Short_Notes/pnpoly.html
            # retrieved Apr 2013
            c = False
            for i, j in segments:
                if ypos < (y[j] - y[i]) * (xpos - x[i]) / (x[j] - x[i]) + y[i]:
                    c = not c
            msk[jj, ii] = bool(c)

    return x, y, msk, xi, yi



def _scale(xs, target_min=0., target_max=1., source_min=None, source_max=None):
    '''Scales from [smin,smax] to [tmin,tmax]'''
    mn = nanmin_wrapper(xs.ravel()) if source_min is None else source_min
    mx = nanmax_wrapper(xs.ravel()) if source_max is None else source_max

    scaled = (xs - mn) / (mx - mn)
    return scaled * (target_max - target_min) + target_min



def flat_surface_curvature2rgba(curvature):
    '''Computes an RGBA colormap in black and white, based on curvature'''
    curvature = curvature_from_any(curvature)

    cmap = plt.get_cmap('binary')

    # invert it so match traditional 'sulcus=dark', then scale to [0,1]
    c = _scale(-curvature)

    return cmap(c)



def _range2min_max(range_, xs):
    '''Converts a range description to a minimum and maximum value

    Parameters
    ----------
    range_: str or float or tuple
        If a tuple (a,b), then this tuple is returned.
        If a float a, then (-a,a) is returned.
        "R(a)", where R(a) denotes the string representation
        of float a, is equivalent to range_=a.
        "R(a)_R(b)" is equivalent to range_=(a,b).
        "R(a)_R(b)%" indicates that the a-th and b-th 
        percentile of xs is taken to define the range.
        "R(a)%" is equivalent to "R(a)_R(100-a)%"
    xs: np.ndarray
        Data array - used to define the range if range_ ends
        with '%'.

    Returns
    -------
    mn, mx: tuple of float
        minimum and maximum value according to the range
    '''

    try:
        r = float(range_)
        if r < 0:
            raise RuntimeError("Single value should be positive")
        return _range2min_max((-r, r), xs)
    except (ValueError, TypeError):
        if isinstance(range_, basestring):
            pat = '(?P<mn>\d*)_?(?P<mx>\d+)?(?P<pct>%)?'

            m = re.match(pat, range_)
            g = m.groups()
            mn, mx, p = g
            if mn != 0 and not mn:
                raise ValueError("Not understood: %s" % range_)
            mn = float(mn)

            percentage = p == '%'
            if percentage:
                xmn = nanmin_wrapper(xs.ravel())
                xmx = nanmax_wrapper(xs.ravel())

                mx = 100 - mn if mx != 0 and not mx else float(mx)

                mn *= .01
                mx *= .01

                mn, mx = np.asarray([mn, mx]) * (xmx - xmn) + xmn
            else:
                mx = float(mx)

        else:
            mn, mx = map(float, range_)
        return mn, mx



def flat_surface_data2rgba(data, range_='2_98%', threshold=None,
                           color_map=None):
    '''Computes an RGBA colormap for surface data'''

    if isinstance(data, Dataset):
        data = data.samples

    cmap = plt.get_cmap(color_map)

    mn, mx = _range2min_max(range_, data)
    scaled = _scale(data, 0., 1., mn, mx)
    rgba = cmap(scaled)
    if threshold is not None:
        mn, mx = _range2min_max(threshold, data)
        to_remove = np.logical_and(data > mn, data < mx)
        rgba[to_remove, :] = np.nan

    return rgba



def curvature_from_any(c):
    '''Reads curvature'''
    if isinstance(c, basestring):
        from mvpa2.support.nibabel import afni_suma_1d

        c = afni_suma_1d.from_any(c)

        # typical SUMA use case: first column has node indices,
        # second column 
        if len(c.shape) > 1 and c.shape[1] == 2 and \
                        set(c[:, 0]) == set(range(1 + int(max(c[:, 0])))):
            cc = c
            n = cc.shape[0]
            c = np.zeros((n,))
            idxs = np.asarray(cc[:, 0], dtype=np.int_)
            c[idxs] = cc[:, 1]

    return np.asarray(c)



class FlatSurfacePlotter(object):
    '''Plots data on a flat surface

    Example
    =======
    flat_surf_fn = 'flat_anat_surface.surf.gii'
    ds = h5load('surface_data.h5py')

    # plot data on surface
    fsp = FlatSurfacePlotter(flat_surf_fn)
    img = fsp(ds.samples[0])

    # plot data with threshold and curvature
    conv_fn='ico16_lh.conv.1D.dset' # from AFNI SUMA's SurfaceMetrics -conv
    fsp_thr=FSP(flat_surf_fn,
                curvature = conv_fn,
                threshold=(.5, .8))
    img_thr=fsp_thr(sl_dset.samples[0])
    '''

    def __init__(self, surface, curvature=None, min_nsteps=500,
                 range_='2_98%', threshold=None, color_map=None,
                 max_deformation=.5):
        '''
        Parameters
        ----------
        surface: surf.Surface
            a flat surface
        curvature: str or np.ndarray
            (Filename of) data representing curvature at each node. 
        min_steps: int
            Minimal side of output plots in pixel
        range_: str or float or tuple
            If a tuple (a,b), then this tuple is returned.
            If a float a, then (-a,a) is returned.
            "R(a)", where R(a) denotes the string representation
            of float a, is equivalent to range_=a.
            "R(a)_R(b)" is equivalent to range_=(a,b).
            "R(a)_R(b)%" indicates that the a-th and b-th 
            percentile of xs is taken to define the range.
            "R(a)%" is equivalent to "R(a)_R(100-a)%"
        threshold: str or float or tuple
            Indicates which values will be shown. Syntax as in range_
        color_map: str
            colormap to use
        max_deformation: float
            maximum deformation to make a non-flat surface flat.
            The normals of each face must have a dot product with the average
            face normal that is not less than (1-max_deformation); otherwise
            an exception is raised. The rationale for this option is that
            certain surfaces may be almost flat, and projecting the vertices
            on a truly flat surface should be fine. On the other hand, surfaces
            that are definitly not flat (such as full cortical surface models)
            should cause an error to be raised when it is attempted to flatten
            them
        '''

        self._surface = surf.from_any(surface)

        if curvature is None:
            self._curvature = None
        else:
            self._curvature = curvature_from_any(curvature)
            if self._surface.nvertices != len(self._curvature):
                raise ValueError("Surface has %d vertices, but curvature "
                                 "has %d values" %
                                 (self._surface.nvertices,
                                  self._curvature.size))

        self._min_nsteps = min_nsteps
        self._range_ = range_
        self._threshold = threshold
        self._color_map = color_map
        self._max_deformation = max_deformation

        self._grid_def = None
        self._underlay = None

    def set_underlay(self, u):
        '''Sets the underlay'''
        self._underlay = u.copy()

    def _set_underlay_from_curvature(self):
        if self._curvature is None:
            raise ValueError("Curvature is not set")

        if self._grid_def is None:
            self._set_grid_def()

        x, y, msk, xi, yi = self._grid_def

        ulay = griddata(x, y, self._curvature, xi, yi, interp='linear')
        ulay[-msk] = np.nan

        rgba = flat_surface_curvature2rgba(ulay)
        self.set_underlay(rgba)

    def _pre_setup(self):
        if self._grid_def is None:
            self._grid_def = flat_surface2grid_mask(self._surface,
                                                    self._min_nsteps,
                                                    self._max_deformation)

        if self._underlay is None and self._curvature is not None:
            self._set_underlay_from_curvature()

    def __call__(self, data):
        '''
        Parameters
        ----------
        data: np.ndarray
            Surface data to be plotted. Should have the same number of data
            points as the surface
        
        Returns
        -------
        rgba: np.ndarray
            Bitmap with RGBA values that can be plotted.
        '''
        self._pre_setup()

        expected_shape = (self._surface.nvertices,)
        if data.shape != expected_shape:
            raise ValueError('data shape was expected to be %s based on '
                             'the number of nodes of the surface, '
                             'found %s' % (
                                 expected_shape, data.shape))

        x, y, msk, xi, yi = self._grid_def
        olay = griddata(x, y, data, xi, yi, interp='linear')
        nan_msk = np.logical_not(msk)
        olay[nan_msk] = np.nan
        o_rgba = flat_surface_data2rgba(olay, self._range_, self._threshold,
                                        self._color_map)
        o_rgba[nan_msk] = np.nan  # apply the mask again, to be sure

        if self._underlay is not None:
            o_msk = -np.isnan(np.sum(o_rgba, 2))

            u_rgba = self._underlay
            u_msk = np.logical_and(np.logical_not(o_msk), msk)

            o_rgba[u_msk] = u_rgba[u_msk]

        return o_rgba
