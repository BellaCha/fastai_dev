#AUTOGENERATED! DO NOT EDIT! File to edit: dev/40_tabular_core.ipynb (unless otherwise specified).

__all__ = ['Tabular', 'TabularPandas', 'TabularProc', 'Categorify', 'Normalize', 'FillStrategy', 'FillMissing',
           'ReadTabBatch', 'TabDataLoader']

#Cell
from ..torch_basics import *
from ..test import *
from ..core import *
from ..data.all import *

#Cell
pd.set_option('mode.chained_assignment','raise')

#Cell
class _TabIloc:
    "Get/set rows by iloc and cols by name"
    def __init__(self,to): self.to = to
    def __getitem__(self, idxs):
        df = self.to.items
        if isinstance(idxs,tuple):
            rows,cols = idxs
            cols = df.columns.isin(cols) if is_listy(cols) else df.columns.get_loc(cols)
        else: rows,cols = idxs,slice(None)
        return self.to.new(df.iloc[rows, cols])

#Cell
class Tabular(CollBase, GetAttr, FilteredBase):
    "A `DataFrame` wrapper that knows which cols are cont/cat/y, and returns rows in `__getitem__`"
    _default='items'
    def __init__(self, df, procs=None, cat_names=None, cont_names=None, y_names=None, is_y_cat=True, splits=None, do_setup=True):
        if splits is None: splits=[range_of(df)]
        df = df.iloc[sum(splits, [])].copy()
        super().__init__(df)

        store_attr(self, 'y_names,is_y_cat')
        self.cat_names,self.cont_names,self.procs = L(cat_names),L(cont_names),Pipeline(procs, as_item=True)
        self.cat_y  = None if not is_y_cat else y_names
        self.cont_y = None if     is_y_cat else y_names
        self.split = len(splits[0])
        if do_setup: self.procs.setup(self)

    def subset(self, i): return self.new(self.items[slice(0,self.split) if i==0 else slice(self.split,len(self))])
    def copy(self): self.items = self.items.copy(); return self
    def new(self, df): return type(self)(df, do_setup=False, **attrdict(self, 'procs','cat_names','cont_names','y_names','is_y_cat'))
    def show(self, max_n=10, **kwargs): display_df(self.all_cols[:max_n])
    def setup(self): self.procs.setup(self)
    def process(self): self.procs(self)
    def iloc(self): return _TabIloc(self)
    def targ(self): return self.items[self.y_names]
    def all_cont_names(self): return self.cont_names + self.cont_y
    def all_cat_names (self): return self.cat_names  + self.cat_y
    def all_col_names (self): return self.all_cont_names + self.all_cat_names
    def n_subsets(self): return 2

properties(Tabular,'iloc','targ','all_cont_names','all_cat_names','all_col_names','n_subsets')

#Cell
class TabularPandas(Tabular):
    def transform(self, cols, f): self[cols] = self[cols].transform(f)

#Cell
def _add_prop(cls, nm):
    @property
    def f(o): return o[list(getattr(o,nm+'_names'))]
    @f.setter
    def fset(o, v): o[getattr(o,nm+'_names')] = v
    setattr(cls, nm+'s', f)
    setattr(cls, nm+'s', fset)

_add_prop(Tabular, 'cat')
_add_prop(Tabular, 'all_cat')
_add_prop(Tabular, 'cont')
_add_prop(Tabular, 'all_cont')
_add_prop(Tabular, 'all_col')

#Cell
class TabularProc(InplaceTransform):
    "Base class to write a non-lazy tabular processor for dataframes"
    def setup(self, items=None):
        super().setup(getattr(items,'train',items))
        # Procs are called as soon as data is available
        return self(items.items if isinstance(items,DataSource) else items)

#Cell
class Categorify(TabularProc):
    "Transform the categorical variables to that type."
    order = 1
    def setups(self, to):
        self.classes = {n:CategoryMap(to.iloc[:,n].items, add_na=(n in to.cat_names)) for n in to.all_cat_names}
    def _apply_cats (self, add, c): return c.cat.codes+add if is_categorical_dtype(c) else c.map(self[c.name].o2i)
    def _decode_cats(self, c): return c.map(dict(enumerate(self[c.name].items)))
    def encodes(self, to):
        to.transform(to.cat_names, partial(self._apply_cats,1))
        to.transform(L(to.cat_y),  partial(self._apply_cats,0))
    def decodes(self, to): to.transform(to.all_cat_names, self._decode_cats)
    def __getitem__(self,k): return self.classes[k]

#Cell
class Normalize(TabularProc):
    "Normalize the continuous variables."
    order = 2
    def setups(self, dsrc): self.means,self.stds = dsrc.conts.mean(),dsrc.conts.std(ddof=0)+1e-7
    def encodes(self, to): to.conts = (to.conts-self.means) / self.stds
    def decodes(self, to): to.conts = (to.conts*self.stds ) + self.means

#Cell
class FillStrategy:
    "Namespace containing the various filling strategies."
    def median  (c,fill): return c.median()
    def constant(c,fill): return fill
    def mode    (c,fill): return c.dropna().value_counts().idxmax()

#Cell
class FillMissing(TabularProc):
    "Fill the missing values in continuous columns."
    def __init__(self, fill_strategy=FillStrategy.median, add_col=True, fill_vals=None):
        if fill_vals is None: fill_vals = defaultdict(int)
        store_attr(self, 'fill_strategy,add_col,fill_vals')

    def setups(self, dsrc):
        self.na_dict = {n:self.fill_strategy(dsrc[n], self.fill_vals[n])
                        for n in pd.isnull(dsrc.conts).any().keys()}

    def encodes(self, to):
        missing = pd.isnull(to.conts)
        for n in missing.any().keys():
            assert n in self.na_dict, f"nan values in `{n}` but not in setup training set"
            to[n].fillna(self.na_dict[n], inplace=True)
            if self.add_col:
                to.loc[:,n+'_na'] = missing[n]
                if n+'_na' not in to.cat_names: to.cat_names.append(n+'_na')

#Cell
class ReadTabBatch(ItemTransform):
    def __init__(self, to): self.to = to
    # TODO: use float for cont targ
    def encodes(self, to): return tensor(to.cats).long(),tensor(to.conts).float(), tensor(to.targ).long()

    def decodes(self, o):
        cats,conts,targs = to_np(o)
        vals = np.concatenate([cats,conts,targs[:,None]], axis=1)
        df = pd.DataFrame(vals, columns=self.to.cat_names+self.to.cont_names+self.to.y_names)
        to = self.to.new(df)
        to = self.to.procs.decode(to)
        return to

#Cell
@typedispatch
def show_batch(x: Tabular, y, its, max_n=10, ctxs=None):
    x.show()

#Cell
@delegates()
class TabDataLoader(TfmdDL):
    do_item = noops
    def __init__(self, dataset, bs=16, shuffle=False, after_batch=None, num_workers=0, **kwargs):
        after_batch = L(after_batch)+ReadTabBatch(dataset)
        super().__init__(dataset, bs=bs, shuffle=shuffle, after_batch=after_batch, num_workers=num_workers, **kwargs)

    def create_batch(self, b): return self.dataset.iloc[b]

TabularPandas._dl_type = TabDataLoader