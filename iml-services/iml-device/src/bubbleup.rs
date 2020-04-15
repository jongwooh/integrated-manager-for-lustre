// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.
use crate::ImlDeviceError;
use device_types::{devices::Device, mount::Mount};
use futures::future::{try_join_all, BoxFuture, FutureExt};
use iml_orm::{
    hosts::ChromaCoreManagedhost,
    targets::ChromaCoreManagedmg,
    tokio_diesel::{AsyncRunQueryDsl as _, OptionalExtension as _},
    volumenode::ChromaCoreVolumenode,
};
use iml_wire_types::Fqdn;
use std::iter::Iterator;

async fn process_mount(
    pool: &iml_orm::DbPool,
    fqdn: &Fqdn,
    mount: Option<&Mount>,
    fs_uuid: Option<&String>,
) -> Result<(), ImlDeviceError> {
    let mount = match mount {
        Some(m) => m,
        None => return Ok(()),
    };

    let mut opts = mount.opts.0.split(",").peekable();

    let mut target = String::from("");
    let mut mgsnid = String::from("");

    while let Some(opt) = opts.next() {
        if opt.starts_with("mgsnode=") {
            mgsnid.push_str(opt.split("=").nth(1).unwrap());
            while opts
                .peek()
                .and_then(|s| if s.contains(&"@") { Some(s) } else { None })
                != None
            {
                mgsnid.push(',');
                mgsnid.push_str(opts.next().unwrap());
            }
        } else if opt.starts_with("svname=") {
            target.push_str(opt.split("=").nth(1).unwrap());
        }
    }

    let host: ChromaCoreManagedhost = match ChromaCoreManagedhost::by_fqdn(&fqdn.0)
        .first_async(pool)
        .await
        .optional()?
    {
        Some(x) => x,
        None => {
            tracing::warn!("Error finding host {}", &fqdn);
            return Ok(());
        }
    };

    let vnode: Option<ChromaCoreVolumenode> =
        ChromaCoreVolumenode::by_host_path(host.id, mount.source.0.to_string_lossy())
            .first_async(pool)
            .await
            .optional()?;
    let vnode = match vnode {
        Some(x) => x,
        None => {
            tracing::warn!(
                "Error finding VolumeNode for {:?} on {}",
                mount.source,
                host.fqdn
            );
            return Ok(());
        }
    };

    if target == "MGS" {
        let mgs = ChromaCoreManagedmg::create(pool, fs_uuid.cloned(), None, &vnode).await?;

        
        
        
    } else {
        let _fs = target.split("-").next().unwrap();
    }
    Ok(())
}

pub fn bubbleup_mount<'a>(
    pool: &'a iml_orm::DbPool,
    fqdn: &'a Fqdn,
    device: &'a Device,
) -> BoxFuture<'a, Result<(), ImlDeviceError>> {
    async move {
        match device {
            Device::Root(root) => {
                let xs = root
                    .children
                    .iter()
                    .map(|dev| async move { bubbleup_mount(pool, fqdn, &dev).await });
                try_join_all(xs).await?;
                Ok(())
            }
            Device::VolumeGroup(vg) => {
                let xs = vg
                    .children
                    .iter()
                    .map(|dev| async move { bubbleup_mount(pool, fqdn, &dev).await });
                try_join_all(xs).await?;
                Ok(())
            }
            Device::Zpool(zpool) => {
                // Zpool's cannot be lustre target, must be zfs volume
                let xs = zpool
                    .children
                    .iter()
                    .map(|dev| async move { bubbleup_mount(pool, fqdn, &dev).await });
                try_join_all(xs).await?;
                Ok(())
            }
            Device::ScsiDevice(dev) => {
                process_mount(
                    pool,
                    fqdn,
                    dev.mount.as_ref(),
                    dev.fs_uuid.as_ref(),
                )
                .await
            }
            Device::Partition(dev) => {
                process_mount(
                    pool,
                    fqdn,
                    dev.mount.as_ref(),
                    dev.fs_uuid.as_ref(),
                )
                .await
            }
            Device::LogicalVolume(dev) => {
                process_mount(
                    pool,
                    fqdn,
                    dev.mount.as_ref(),
                    dev.fs_uuid.as_ref(),
                )
                .await
            }
            Device::MdRaid(dev) => {
                process_mount(
                    pool,
                    fqdn,
                    dev.mount.as_ref(),
                    dev.fs_uuid.as_ref(),
                )
                .await
            }
            Device::Mpath(dev) => {
                process_mount(
                    pool,
                    fqdn,
                    dev.mount.as_ref(),
                    dev.fs_uuid.as_ref(),
                )
                .await
            }
            Device::Dataset(dev) => {
                // @@
                //let fs_uuid = dev.props
                //let size = dev.props
                //process_mount(pool, fqdn, dev.mount.as_ref(), fs_uuid.as_ref()),
                tracing::error!(
                    "NYI: no processing of ZFS Datasets for magic import: {:?}",
                    dev
                );
                Ok(())
            }
        }
    }
    .boxed()
}
