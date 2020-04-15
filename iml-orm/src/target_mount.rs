// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

pub use crate::models::ChromaCoreManagedtargetmount;
use crate::schema::chroma_core_managedtargetmount as mtm;
use diesel::{dsl, prelude::*};

pub type Table = mtm::table;
pub type NotDeleted = dsl::Eq<mt::not_deleted, bool>;
//pub type WithFqdn<'a> = dsl::And<dsl::Eq<mh::fqdn, &'a str>, NotDeleted>;
//pub type ByFqdn<'a> = dsl::Filter<Table, WithFqdn<'a>>;

impl ChromaCoreManagedtargetmount {
    pub fn all() -> Table {
        mtm::table
    }
    pub fn not_deleted() -> NotDeleted {
        mtm::not_deleted.eq(true)
    }
    pub fn with_host_id(name: &str) -> WithFqdn<'_> {
        mh::fqdn.eq(name).and(Self::not_deleted())
    }
    pub fn by_fqdn<'a>(fqdn: &'a str) -> ByFqdn<'a> {
        Self::all().filter(Self::with_fqdn(fqdn))
    }
    pub fn is_setup(&self) -> bool {
        ["monitored", "managed", "working"]
            .iter()
            .find(|&x| x == &self.state)
            .is_some()
    }
}
