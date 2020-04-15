// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

pub use crate::models::{ChromaCoreManagedmg, ChromaCoreManagedtarget};
use crate::{
    django::DjangoContentType,
    schema::{chroma_core_managedmgs as mgs, chroma_core_managedtarget as mt},
    tokio_diesel::{AsyncError, AsyncRunQueryDsl as _},
    volumenode::ChromaCoreVolumenode,
    DbPool,
};
use chrono::offset::Utc;
use diesel::{dsl, prelude::*};

// Managed Target
pub type NotDeleted = dsl::Eq<mt::not_deleted, bool>;
pub type WithVolume = dsl::And<dsl::Eq<mt::volume_id, i32>, NotDeleted>;
pub type ByVolume = dsl::Filter<mt::table, WithVolume>;

// Managed MGS
pub type WithTarget = dsl::Eq<mgs::managedtarget_ptr_id, i32>; 
pub type ByTarget = dsl::Filter<mgs::table, WithTarget>;

impl ChromaCoreManagedtarget {
    pub fn all() -> mt::table {
        mt::table
    }
    pub fn not_deleted() -> NotDeleted {
        mt::not_deleted.eq(true)
    }
    pub fn with_volume(volume: i32) -> WithVolume {
        mt::volume_id.eq(volume).and(Self::not_deleted())
    }
    pub fn by_volume(volume: i32) -> ByVolume {
        Self::all().filter(Self::with_volume(volume))
    }

    pub async fn create(
        pool: &DbPool,
        name: Option<String>,
        uuid: Option<String>,
        ha_label: Option<String>,
        vnode: &ChromaCoreVolumenode,
    ) -> Result<Self, AsyncError> {
        let content_id: i32 = DjangoContentType::id_by_model("managedtarget")
            .first_async(pool)
            .await?;

        dsl::insert_into(mt::table)
            .values((
                mt::state.eq("mounted".to_string()),
                mt::state_modified_at.eq(Utc::now()),
                mt::immutable_state.eq(true),
                mt::name.eq(name),
                mt::uuid.eq(uuid),
                mt::ha_label.eq(ha_label),
                mt::volume_id.eq(vnode.volume_id),
                mt::content_type_id.eq(content_id),
            ))
            .execute_async(pool)
            .await?;

        Self::by_volume(vnode.volume_id)
            .first_async(pool)
            .await
    }
}

impl ChromaCoreManagedmg {
    pub fn all() -> mgs::table {
        mgs::table
    }
    pub fn with_target(target: i32) -> WithTarget {
        mgs::managedtarget_ptr_id.eq(target)
    }
    pub fn by_target(target: i32) -> ByTarget {
        Self::all().filter(Self::with_target(target))
    }
    
    pub async fn create(
        pool: &DbPool,
        uuid: Option<String>,
        ha_label: Option<String>,
        vnode: &ChromaCoreVolumenode,
    ) -> Result<Self, AsyncError> {
        let target =
            ChromaCoreManagedtarget::create(pool, Some("MGS".into()), uuid, ha_label, vnode)
                .await?;
        let zero: i32 = 0;

        dsl::insert_into(mgs::table)
            .values((
                mgs::managedtarget_ptr_id.eq(target.id),
                mgs::conf_param_version.eq(zero),
                mgs::conf_param_version_applied.eq(zero),
            ))
            .returning(mgs::table::all_columns())
            .get_result_async(pool)
            .await
    }
}
