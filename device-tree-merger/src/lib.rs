use device_types::devices::Device;
use iml_wire_types::Fqdn;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    borrow::{BorrowMut, Cow},
    fmt::{Debug, Display},
    marker::PhantomData,
};
use treediff::{
    tools::{DefaultMutableFilter, MutableFilter},
    Delegate, Mutable,
};

#[derive(Clone, Debug, PartialEq, Deserialize, Serialize)]
pub struct MyMerger<K, V, BF, F> {
    cursor: Vec<K>,
    inner: V,
    fqdn: Fqdn,
    filter: BF,
    devices: Vec<(Fqdn, V)>,
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

    pub fn into_devices(self) -> Vec<(Fqdn, V)> {
        let mut result = self.devices;
        result.push((self.fqdn, self.inner));
        result
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
    pub fn with_state(v: V, f: BF, fqdn: Fqdn, devices: Vec<(Fqdn, V)>) -> Self {
        MyMerger {
            inner: v,
            fqdn,
            cursor: Vec::new(),
            filter: f,
            devices,
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
            keys,
            old,
            new,
            target
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
            keys,
            removed,
            target
        );
        None
    }
}

// TODO: Collect the path to the parent and return it as well
fn collect_virtual_device_parents<'d>(
    d: &'d Value,
    level: usize,
    parent: Option<&'d Value>,
) -> Vec<&'d Value> {
    let mut results = vec![];
    if is_virtual(d) {
        tracing::debug!(
            "Collecting parent {} of {}",
            parent.map(|x| to_display(x)).unwrap_or("None".into()),
            to_display(d)
        );
        vec![parent.expect("Tried to push to parents the parent of the Root, which doesn't exist")]
    } else {
        let o = d.as_object().unwrap();
        let so = o
            .get("Root")
            .or_else(|| o.get("ScsiDevice"))
            .or_else(|| o.get("Partition"))
            .or_else(|| o.get("Mpath"));
        if let Some(so) = so {
            let cs = &so["children"];
            let cs = cs.as_array().unwrap();
            for c in cs {
                results.extend(collect_virtual_device_parents(c, level + 1, Some(d)));
            }
            results
        } else {
            vec![]
        }
    }
}

pub fn is_virtual(d: &Value) -> bool {
    let o = d.as_object().unwrap();
    // TODO: Rewrite with `contains_key`
    o.get("Dataset")
        .or_else(|| o.get("LogicalVolume"))
        .or_else(|| o.get("MdRaid"))
        .or_else(|| o.get("VolumeGroup"))
        .or_else(|| o.get("Zpool"))
        .is_some()
}

pub fn to_display(d: &Value) -> String {
    let mut i = d.as_object().unwrap().iter();
    let (k, v) = i.next().unwrap();
    match (k.as_ref(), v) {
        ("Root", v) => format!(
            "Root: children: {}",
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("ScsiDevice", v) => format!(
            "ScsiDevice: serial: {}, children: {}",
            v.as_object().unwrap()["serial"].as_str().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("Partition", v) => format!(
            "Partition: serial: {}, children: {}",
            v.as_object().unwrap()["serial"].as_str().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("MdRaid", v) => format!(
            "MdRaid: uuid: {}, children: {}",
            v.as_object().unwrap()["uuid"].as_str().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("Mpath", v) => format!(
            "Mpath: serial: {}, children: {}",
            v.as_object().unwrap()["serial"].as_str().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("VolumeGroup", v) => format!(
            "VolumeGroup: uuid: {}, children: {}",
            v.as_object().unwrap()["uuid"].as_str().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("LogicalVolume", v) => format!(
            "LogicalVolume: uuid: {}, children: {}",
            v.as_object().unwrap()["uuid"].as_str().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("Zpool", v) => format!(
            "Zpool: guid: {}, children: {}",
            v.as_object().unwrap()["guid"].as_u64().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        ("Dataset", v) => format!(
            "Dataset: guid: {}, children: {}",
            v.as_object().unwrap()["guid"].as_u64().unwrap(),
            v.as_object().unwrap()["children"].as_array().unwrap().len(),
        ),
        _ => unreachable!(),
    }
}
