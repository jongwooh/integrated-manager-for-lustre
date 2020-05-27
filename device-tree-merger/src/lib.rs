use treediff::{
    tools::{DefaultMutableFilter, MutableFilter},
    Delegate, Mutable,
};
use std::{
    borrow::{BorrowMut, Cow},
    fmt::{Debug, Display},
    marker::PhantomData,
};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
pub struct MyMerger<K, V, BF, F> {
    cursor: Vec<K>,
    inner: V,
    filter: BF,
    _d: PhantomData<F>,
}
impl<K, V, BF, F> MutableFilter for MyMerger<K, V, BF, F> {}

fn appended<K>(keys: &[K], k: Option<&K>) -> Vec<K>
where
    K: Clone,
{
    let mut keys = Vec::from(keys);
    if let Some(k) = k {
        keys.push(k.clone());
    }
    keys
}

impl<'a, K, V, F, BF> Delegate<'a, K, V> for MyMerger<K, V, BF, F>
where
    V: Mutable<Key = K, Item = V> + Clone + Debug + 'a,
    K: Clone + Display + Debug,
    F: MutableFilter,
    BF: BorrowMut<F>,
{
    fn push(&mut self, k: &K) {
        self.cursor.push(k.clone());
    }
    fn pop(&mut self) {
        self.cursor.pop();
    }
    fn removed<'b>(&mut self, k: &'b K, v: &'a V) {
        let keys = appended(&self.cursor, Some(k));
        match self
            .filter
            .borrow_mut()
            .resolve_removal(&keys, v, &mut self.inner)
        {
            Some(nv) => self.inner.set(&keys, &nv),
            None => self.inner.remove(&keys),
        }
    }
    fn added<'b>(&mut self, k: &'b K, v: &'a V) {
        self.inner.set(&appended(&self.cursor, Some(k)), v);
    }
    fn unchanged<'b>(&mut self, v: &'a V) {
        self.inner.set(&self.cursor, v)
    }
    fn modified<'b>(&mut self, old: &'a V, new: &'a V) {
        let keys = appended(&self.cursor, None);
        match self
            .filter
            .borrow_mut()
            .resolve_conflict(&keys, old, new, &mut self.inner)
        {
            Some(v) => self.inner.set(&keys, &v),
            None => self.inner.remove(&keys),
        }
    }
}

impl<K, V, BF, F> MyMerger<K, V, BF, F> {
    pub fn into_inner(self) -> V {
        self.inner
    }

    pub fn filter_mut(&mut self) -> &mut BF {
        &mut self.filter
    }

    pub fn filter(&self) -> &BF {
        &self.filter
    }
}

impl<K, V, BF, F> AsRef<V> for MyMerger<K, V, BF, F> {
    fn as_ref(&self) -> &V {
        &self.inner
    }
}

impl<'a, V, BF, F> MyMerger<V::Key, V, BF, F>
where
    V: Mutable + 'a + Clone,
    F: MutableFilter,
    BF: BorrowMut<F>,
{
    pub fn with_filter(v: V, f: BF) -> Self {
        MyMerger {
            inner: v,
            cursor: Vec::new(),
            filter: f,
            _d: PhantomData,
        }
    }
}

impl<'a, V> From<V> for MyMerger<V::Key, V, DefaultMutableFilter, DefaultMutableFilter>
where
    V: Mutable + 'a + Clone,
{
    fn from(v: V) -> Self {
        Self {
            inner: v,
            cursor: Vec::new(),
            filter: DefaultMutableFilter,
            _d: PhantomData,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
pub struct MyFilter;
impl MutableFilter for MyFilter {
    fn resolve_conflict<'a, K: Clone + Debug + Display, V: Clone + Debug>(
        &mut self,
        keys: &[K],
        old: &'a V,
        new: &'a V,
        target: &mut V,
    ) -> Option<Cow<'a, V>> {
        tracing::info!(
            "keys: {:?}, old: {:?}, new: {:?}, target: {:?}",
            keys, old, new, target
        );
        Some(Cow::Borrowed(new))
    }

    fn resolve_removal<'a, K: Clone + Debug + Display, V: Clone + Debug>(
        &mut self,
        keys: &[K],
        removed: &'a V,
        target: &mut V,
    ) -> Option<Cow<'a, V>> {
        tracing::info!(
            "keys: {:?}, removed: {:?}, target: {:?}",
            keys, removed, target
        );
        None
    }
}
