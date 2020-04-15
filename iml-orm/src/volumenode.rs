// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

pub use crate::models::ChromaCoreVolumenode;
use crate::schema::chroma_core_volumenode as vn;
use diesel::{dsl, prelude::*};

pub type Table = vn::table;
pub type NotDeleted = dsl::Eq<vn::not_deleted, bool>;
pub type WithHost = dsl::Eq<vn::host_id, i32>;
pub type WithHostPath = dsl::And<dsl::And<dsl::Eq<vn::path, String>, WithHost>, NotDeleted>;
pub type ByHostPath = dsl::Filter<Table, WithHostPath>;

//pub type WithHostPaths<'a> = dsl::And<dsl::And<dsl::Eq<vn::path, &'a[&'a str]>, WithHost>, NotDeleted>;
//pub type ByHostPaths<'a> = dsl::Filter<Table, WithHostPaths<'a>>;

impl ChromaCoreVolumenode {
    pub fn all() -> Table {
        vn::table
    }
    pub fn not_deleted() -> NotDeleted {
        vn::not_deleted.eq(true)
    }
    pub fn with_host(host_id: i32) -> WithHost {
        vn::host_id.eq(host_id)
    }

    pub fn with_host_path(host_id: i32, path: impl ToString) -> WithHostPath {
        vn::path
            .eq(path.to_string())
            .and(Self::with_host(host_id))
            .and(Self::not_deleted())
    }
    pub fn by_host_path(host_id: i32, path: impl ToString) -> ByHostPath {
        Self::all().filter(Self::with_host_path(host_id, path))
    }
}
