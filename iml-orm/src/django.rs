// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

pub use crate::models::DjangoContentType;
use crate::schema::django_content_type as ct;
use diesel::{dsl, prelude::*};

pub type Table = ct::table;
pub type WithApp = dsl::Eq<ct::app_label, String>;
pub type WithModel = dsl::And<dsl::Eq<ct::model, String>, WithApp>;
pub type ByModel = dsl::Filter<Table, WithModel>;
pub type IdByModel = dsl::Select<dsl::Filter<Table, WithModel>, ct::id>;

impl DjangoContentType {
    pub fn all() -> Table {
        ct::table
    }
    pub fn with_app(name: impl ToString) -> WithApp {
        ct::app_label.eq(name.to_string())
    }
    pub fn with_model(name: impl ToString) -> WithModel {
        ct::model
            .eq(name.to_string())
            .and(Self::with_app("chroma_core"))
    }
    pub fn by_model(model: impl ToString) -> ByModel {
        Self::all().filter(Self::with_model(model))
    }
    pub fn id_by_model(model: impl ToString) -> IdByModel {
        Self::all().filter(Self::with_model(model)).select(ct::id)
    }
}
