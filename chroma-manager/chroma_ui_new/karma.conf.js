/* jshint node: true */

var util = require('util');

module.exports = function setConfig (config) {
  'use strict';

  function bound(format) {
    return util.format.bind(util, format);
  }

  var sourceDir = bound('source/chroma_ui/%s');
  var bowerDir = bound(sourceDir('bower_components/%s'));
  var vendorDir = bound(sourceDir('vendor/%s'));
  var imlDir = bound(sourceDir('iml/%s'));
  var commonDir = bound(sourceDir('common/%s'));
  var testDir = bound('test/%s');
  var uiModulesDir = bound('../ui-modules/%s');
  var isomorphicModulesDir = bound(uiModulesDir('isomorphic/%s'));
  var angularComponentsDir = bound(uiModulesDir('angular/%s'));

  config.set({

    // base path, that will be used to resolve files and exclude
    basePath: '',


    // frameworks to use
    frameworks: ['jasmine'],


    // list of files / patterns to load in the browser
    files: [
      bowerDir('jasmine-stealth/dist/jasmine-stealth.js'),
      bowerDir('jquery/dist/jquery.js'),
      bowerDir('angular/angular.js'),
      bowerDir('angular-resource/angular-resource.js'),
      bowerDir('angular-bindonce/bindonce.js'),
      bowerDir('angular-route/angular-route.js'),
      bowerDir('angular-route-segment/build/angular-route-segment.js'),
      bowerDir('lodash/dist/lodash.js'),
      bowerDir('moment/moment.js'),
      bowerDir('twix/bin/twix.js'),
      bowerDir('d3/d3.js'),
      bowerDir('angular-bootstrap/ui-bootstrap-tpls.js'),
      isomorphicModulesDir('fp/index.js'),
      isomorphicModulesDir('lodash-mixins/index.js'),
      vendorDir('**/*.js'),
      commonDir('**/*-module.js'),
      commonDir('**/*.js'),
      commonDir('**/*.html'),
      imlDir('**/*-module.js'),
      imlDir('**/*.js'),
      imlDir('**/*.html'),
      bowerDir('angular-mocks/angular-mocks.js'),
      bowerDir('timecop/timecop-0.1.1.js'),
      testDir('mocks/mock.js'),
      testDir('**/*-module.js'),
      testDir('data-fixtures/data-fixtures-module.js'),
      testDir('data-fixtures/**/*.js'),
      testDir('fixtures/fixtures.js'),
      testDir('fixtures/**/*.js'),
      testDir('global-setup.js'),
      testDir('matchers/**/*.js'),
      bowerDir('jasmine-object-containing/jasmine-object-containing.js'),
      bowerDir('jasmine-n-matchers/jasmine-n-matchers.js'),
      testDir('**/*.js'),
      testDir('templates/**/*.html'),
      angularComponentsDir('src/**/*.js'),
      angularComponentsDir('test/**/*.js')
    ],

    // list of files to exclude
    exclude: [
      imlDir('iml.js'),
      testDir('selenium/**/*'),
      testDir('integration/*')
    ],


    // test results reporter to use
    // possible values: 'dots', 'progress', 'junit', 'growl', 'coverage'
    reporters: ['dots'],

    // Only used if junit reporter activated (ex "--reporters junit" on the command line)
    junitReporter: {
      suite: 'karma-tests (new ui)'
    },


    preprocessors: {
      '**/*.html': ['ng-html2js']
    },

    ngHtml2JsPreprocessor: {
      moduleName: 'templates',
      cacheIdFromPath: function (filepath) {
        return filepath
          .replace(/^source\/chroma_ui\//, '')
          .replace(/^test\/templates\//, '');
      }
    },

    // web server port
    port: 9876,


    // enable / disable colors in the output (reporters and logs)
    colors: true,


    // level of logging
    // possible values: config.LOG_DISABLE || config.LOG_ERROR || config.LOG_WARN || config.LOG_INFO || config.LOG_DEBUG
    logLevel: config.LOG_INFO,


    // enable / disable watching file and executing tests whenever any file changes
    autoWatch: false,


    // Start these browsers, currently available:
    // - Chrome
    // - ChromeCanary
    // - Firefox
    // - Opera
    // - Safari (only Mac)
    // - PhantomJS
    // - IE (only Windows)
    browsers: ['Chrome'],


    // If browser does not capture in given timeout [ms], kill it
    captureTimeout: 60000,


    // Continuous Integration mode
    // if true, it capture browsers, run tests and exit
    singleRun: false
  });
};
