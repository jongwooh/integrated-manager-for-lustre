//
// INTEL CONFIDENTIAL
//
// Copyright 2013-2015 Intel Corporation All Rights Reserved.
//
// The source code contained or described herein and all documents related
// to the source code ("Material") are owned by Intel Corporation or its
// suppliers or licensors. Title to the Material remains with Intel Corporation
// or its suppliers and licensors. The Material contains trade secrets and
// proprietary and confidential information of Intel or its suppliers and
// licensors. The Material is protected by worldwide copyright and trade secret
// laws and treaty provisions. No part of the Material may be used, copied,
// reproduced, modified, published, uploaded, posted, transmitted, distributed,
// or disclosed in any way without Intel's prior express written permission.
//
// No license under any patent, copyright, trade secret or other intellectual
// property right is granted to or conferred upon you by disclosure or delivery
// of the Materials, either expressly, by implication, inducement, estoppel or
// otherwise. Any license under such intellectual property rights must be
// express and approved by Intel in writing.


/* Subclass of Backbone.Collection which provides
 * methods for working with URIs instead of IDs */
var UriCollection = Backbone.Collection.extend({
  fetch_uris: function(uris, success) {
    var ids = [];
    $.each(uris, function(i, uri) {
      var tokens = uri.split("/");
      var id = tokens[tokens.length - 2];
      ids.push(id);
    });
    if (ids.length) {
      this.fetch({data: {limit: 0, id__in: ids}, success: success})
    } else {
      success()
    }
  }
});

var Job = Backbone.Model.extend({
  urlRoot: "/api/job/"
});

var JobCollection = UriCollection.extend({
  model: Job,
  url: "/api/job/"
});

var Step = Backbone.Model.extend({
  urlRoot: "/api/step/"
});

var StepCollection = UriCollection.extend({
  model: Step,
  url: "/api/step/"
});



var Command = Backbone.Model.extend({
  jobTree: function(jobs) {
    // For each job ID, the job dict
    var id_to_job = {};
    // For each job ID, which other jobs in this command wait for me
    var id_to_what_waits = {};

    $.each(jobs, function(i, job) {
      id_to_job[job.resource_uri] = job;
      id_to_what_waits[job.resource_uri] = [];
    });

    $.each(jobs, function(i, job) {
      $.each(job.wait_for, function (i, job_id) {
        if (id_to_job[job_id]) {
          id_to_what_waits[job_id].push(job.resource_uri);
        }
      });
    });

    var shallowest_occurrence = {};
    function jobChildren(root_job, depth) {
      if (depth == undefined) {
        depth = 0
      } else {
        depth = depth + 1
      }

      if (shallowest_occurrence[root_job.resource_uri] == undefined || shallowest_occurrence[root_job.resource_uri] > depth) {
        shallowest_occurrence[root_job.resource_uri] = depth;
      }

      var children = [];
      $.each(root_job.wait_for, function(i, job_id) {
        var awaited_job = id_to_job[job_id];
        if (awaited_job) {
          children.push(jobChildren(awaited_job, depth));
        }
      });
      return $.extend({children: children}, root_job)
    }

    var tree = [];
    $.each(jobs, function(i, job) {
      var what_waits = id_to_what_waits[job.resource_uri];
      if (what_waits.length == 0) {
        // Nothing's waiting for me, I'm top level
        tree.push(jobChildren(job))
      }
    });

    // A job may only appear at its highest depth
    // e.g. stop a filesystem stops the MDT, making the filesystem unavailable, which the OST waits for
    // e.g. stop a filesystem stops the OST, making the filesystem unavailable, which the MDT waits for
    function prune(root_job, depth) {
      if (depth == undefined) {
        depth = 0
      } else {
        depth = depth + 1
      }

      $.each(root_job.children, function(i, child) {
        var child_depth = depth + 1;
        if (shallowest_occurrence[child.resource_uri] < child_depth) {
          delete root_job.children[i]
        } else {
          prune(child, depth)
        }
      });
    }

    $.each(tree, function(i, root) {
      prune(root);
    });

    return tree;
  },
  fetch: function(options) {
    var outer_success = options.success;
    options.success = function(model, response) {
      var job_ids = [];
      $.each(model.attributes.jobs, function(i, job_uri) {
        var tokens = job_uri.split("/");
        var job_id = tokens[tokens.length - 2];
        job_ids.push(job_id);
      });
      var collection = new JobCollection();
      if (job_ids.length == 0) {
        model.set('jobs_full', []);
        model.set('jobs_tree', []);
        if (outer_success) {
          outer_success(model, response);
        }
      } else {
        collection.fetch({data: {id__in: job_ids, limit: 0}, success: function(c, r) {
          var jobs = c.toJSON();
          model.set('jobs_full', jobs);
          model.set('jobs_tree', model.jobTree(jobs));
          if (outer_success) {
            outer_success(model, response);
          }
        }})
      }
    };

    Backbone.Model.prototype.fetch.apply(this, [options])
  },
  urlRoot: "/api/command/"
});

var CommandDetail = Backbone.View.extend({
  className: 'command_dialog',
  template: _.template($('#command_detail_template').html()),
  initialize: function() {
    _.bindAll(this, 'render');
    this.model.bind('change', this.render);
  },
  render: function() {
    var command_detail_view = this;
    var rendered = this.template(this.model.toJSON());
    $(this.el).addClass('command_detail')
    $(this.el).find('.ui-dialog-content').html(rendered);

    var update_period = 1000;
    var command_model = this.model;
    var view = this;
    function update() {
      if (view.el.parentNode != null) {
        command_model.fetch({
          success: function() {
            if (!command_model.get('complete')){
              setTimeout(update, update_period);
            }
          }
        });
      }
    }
    if (!command_model.get('complete')) {
      setTimeout(update, update_period);
    }

    $(this.el).find('.job_state_transition').each(function() {
      var link = $(this);
      link.button();
      link.click(function(ev) {
        var job = link.data('job');
        job.state = link.data('state');
        Api.put(job.resource_uri, job,
          success_callback = function(data) {
            command_detail_view.model.fetch({success:function(){
              command_detail_view.render();
            }});
            // TODO: reload the command and its job, and redraw the UI
          }
        );
        ev.preventDefault();
      });
    });
    return this;
  }
});


var JobDetail = Backbone.View.extend({
  className: 'job_dialog',
  template: _.template($('#job_detail_template').html()),
  openStepIndex: function(job_steps) {
    // returns the first indexed job.step that isn't in state "success"
    // ie errors and currently running steps
    // defaults to 0 on not found
    for ( var i = 0; i < job_steps.length ; i++) {
      if (job_steps[i].state !== 'success') {
        return i;
      }
    }
    return 0;
  },
  render: function() {
    var steps = new StepCollection();

    steps.fetch_uris(this.model.attributes.steps, function() {
      var job = this.model.toJSON();
      job.steps = steps.toJSON();
      var wait_for = new JobCollection();

      wait_for.fetch_uris(this.model.attributes.wait_for, function() {
        job.wait_for = wait_for.toJSON();

        var rendered = this.template({job: job});
        var el = $(this.el);
        el.find('.ui-dialog-content').html(rendered);
        el.find('.dialog_tabs').tabs();
        if (job.wait_for.length == 0) {
          el.find('.dialog_tabs').tabs('disable', 'dependencies');
        }

        // make an accordian if there's more than one step
        // open the first step if all steps successful
        // open the first non-successful step otherwise
        if (job.steps.length > 1) {
          el.find('.job_step_list').accordion({
            collapsible : true,
            active      : this.openStepIndex(job.steps)
          });
        }
      }.bind(this));
    }.bind(this));

    return this;
  }
});