"""Minimal sirf.STIR-compatible layer on top of STIR 6.5 Python (CUDA build, parallelproj).

Only the API used by PETRIC2 petric.py and the Speedy psv main.py is provided.
Images are numpy arrays in host memory (SIRF ImageData also keeps the STIR image in host memory);
every call into STIR converts numpy <-> STIR image, timed separately as 'shim_convert'.
"""
import numpy as np
import stir
import stir.extra as _sx
from prof import sec


def set_max_omp_threads(n):
    stir.set_num_threads(int(n))


def set_verbosity(v):
    pass


class MessageRedirector:
    def __init__(self, *a, **k):
        pass


def _np(s):
    return np.ascontiguousarray(_sx.to_numpy(s), dtype=np.float32)


def proj_to_numpy(pd):
    a = pd.to_array()
    return np.asarray(_sx.to_numpy(a))


class ImageData:
    def __init__(self, src=None, _arr=None, _tmpl=None):
        if isinstance(src, str):
            with sec('read_data'):
                s = stir.FloatVoxelsOnCartesianGrid.read_from_file(src)
                self._tmpl = s
                self.arr = _np(s).copy()
        else:
            self._tmpl = _tmpl
            self.arr = _arr

    def _new(self, arr):
        return ImageData(_arr=arr, _tmpl=self._tmpl)

    def to_stir(self):
        with sec('shim_convert'):
            s = self._tmpl.get_empty_copy()
            s.fill(np.ascontiguousarray(self.arr).ravel())
            return s

    def _from_stir(self, s):
        with sec('shim_convert'):
            return self._new(_np(s).copy())

    @property
    def shape(self):
        return self.arr.shape

    @property
    def spacing(self):
        v = self._tmpl.get_voxel_size()
        return (float(v[1]), float(v[2]), float(v[3]))

    def dimensions(self):
        return self.arr.shape

    def as_array(self):
        return self.arr.copy()

    def asarray(self, copy=True):
        return self.arr.copy() if copy else self.arr

    def clone(self):
        with sec('image_ops'):
            return self._new(self.arr.copy())

    def get_uniform_copy(self, v=0.0):
        with sec('image_ops'):
            return self._new(np.full_like(self.arr, v))

    def allocate(self, v=0.0):
        return self.get_uniform_copy(v)

    def fill(self, v):
        with sec('image_ops'):
            if isinstance(v, ImageData):
                v = v.arr
            if np.ndim(v):
                self.arr[...] = np.asarray(v, dtype=np.float32).reshape(self.arr.shape)
            else:
                self.arr[...] = v
        return self

    def max(self):
        return float(self.arr.max())

    def norm(self):
        return float(np.linalg.norm(self.arr.ravel()))

    def maximum(self, v, out=None):
        with sec('image_ops'):
            b = v.arr if isinstance(v, ImageData) else v
            if out is None:
                return self._new(np.maximum(self.arr, b))
            np.maximum(self.arr, b, out=out.arr)
            return out

    def write(self, fname):
        pass

    # arithmetic: SIRF does these in C++ on the CPU
    def _op(self, o, f, reverse=False):
        with sec('image_ops'):
            b = o.arr if isinstance(o, ImageData) else np.float32(o)
            r = f(b, self.arr) if reverse else f(self.arr, b)
            return self._new(r.astype(np.float32, copy=False))

    def __add__(self, o): return self._op(o, np.add)
    def __radd__(self, o): return self._op(o, np.add, True)
    def __sub__(self, o): return self._op(o, np.subtract)
    def __rsub__(self, o): return self._op(o, np.subtract, True)
    def __mul__(self, o): return self._op(o, np.multiply)
    def __rmul__(self, o): return self._op(o, np.multiply, True)
    def __truediv__(self, o): return self._op(o, np.divide)
    def __rtruediv__(self, o): return self._op(o, np.divide, True)
    def __neg__(self): return self._op(-1.0, np.multiply)

    def __iadd__(self, o):
        with sec('image_ops'):
            b = o.arr if isinstance(o, ImageData) else np.float32(o)
            np.add(self.arr, b, out=self.arr)
        return self

    def __isub__(self, o):
        with sec('image_ops'):
            b = o.arr if isinstance(o, ImageData) else np.float32(o)
            np.subtract(self.arr, b, out=self.arr)
        return self


class AcquisitionData:
    @staticmethod
    def set_storage_scheme(s):
        pass

    def __init__(self, path):
        with sec('read_data'):
            self.pd = stir.ProjDataInMemory(stir.ProjData.read_from_file(path))

    @property
    def shape(self):
        p = self.pd
        return (1, p.get_num_sinograms(), p.get_num_views(), p.get_num_tangential_poss())

    def get_info(self):
        return self.pd.get_proj_data_info().parameter_info()

    def as_array(self):
        return proj_to_numpy(self.pd)


class SeparableGaussianImageFilter:
    def __init__(self):
        self.f = stir.SeparableGaussianImageFilter3DFloat()

    def set_fwhms(self, fw):
        c = stir.Float3BasicCoordinate()
        c[1], c[2], c[3] = float(fw[0]), float(fw[1]), float(fw[2])
        self.f.set_fwhms(c)

    def set_up(self, img):
        self.f.set_up(img.to_stir())

    def process(self, img):
        with sec('gauss_filter'):
            s = img.to_stir()
            self.f.apply(s)
            return img._from_stir(s)


class TruncateToCylinderProcessor:
    def process(self, img):
        s = img.to_stir()
        p = stir.TruncateToCylindricalFOVImageProcessor3DFloat()
        p.set_up(s)
        p.apply(s)
        return img._from_stir(s)


class RelativeDifferencePrior:
    _cls = stir.RelativeDifferencePrior3DFloat

    def __init__(self):
        self.p = self._cls()
        self._keep = []

    def set_epsilon(self, e): self.p.set_epsilon(float(e))
    def get_epsilon(self): return self.p.get_epsilon()
    def get_gamma(self): return self.p.get_gamma()
    def set_penalisation_factor(self, v): self.p.set_penalisation_factor(float(v))
    def get_penalisation_factor(self): return self.p.get_penalisation_factor()

    def set_kappa(self, k):
        s = k.to_stir()
        self._keep.append(s)
        self.p.set_kappa_sptr(s)

    def set_up(self, img):
        self.p.set_up(img.to_stir())

    def gradient(self, img):
        with sec('prior_gradient'):
            s = img.to_stir()
            g = s.get_empty_copy()
            self.p.compute_gradient(g, s)
            return img._from_stir(g)


class CudaRelativeDifferencePrior(RelativeDifferencePrior):
    _cls = stir.CudaRelativeDifferencePrior3DFloat
