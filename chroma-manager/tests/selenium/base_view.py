

import logging
import time
from selenium.common.exceptions import NoSuchElementException

from tests.selenium.base import find_visible_element_by_css_selector, element_visible, wait_for_transition, wait_for_element
from tests.selenium.utils.constants import wait_time


log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler())
log.setLevel(logging.DEBUG)


class BaseView(object):
    def __init__(self, driver):
        self.driver = driver
        self.log = log

        self.long_wait = wait_time['long']
        self.medium_wait = wait_time['medium']
        self.standard_wait = wait_time['standard']

    def quiesce(self):
        for i in xrange(self.medium_wait):
            busy = self.driver.execute_script('return ($.active != 0);')
            if not busy:
                self.log.debug('quiesced in %s iterations' % i)
                return
            else:
                time.sleep(1)

        raise RuntimeError("Timed out waiting for API operations to complete after %s seconds" % self.medium_wait)

    def wait_for_element(self, selector):
        wait_for_element(self.driver, selector, self.standard_wait)

    def get_visible_element_by_css_selector(self, selector):
        """Return an element matching the selector which is visible, or raise
        an exception if no such element exists.  Useful when there is
        more than one element in the DOM matching the selector but you
        want to find the one that is currently on-screen."""

        element = find_visible_element_by_css_selector(self.driver, selector)
        if not element:
            raise RuntimeError("No visible element match %s" % selector)
        return element

    def _find_state_button(self, container, state):
        # Iterating because selenium doesn't seem to correctly apply a [data-state=xxx] selector
        buttons = container.find_elements_by_css_selector('button')
        for button in buttons:
            if button.get_attribute('data-state') == state:
                return button
        raise NoSuchElementException("No button (of %s buttons) found with state %s" % (len(buttons), state))

    def click_command_button(self, container, state):
        """Find a button within `container` that is a state transition
        to `state`, click it, and wait for the transition to complete"""

        button = self._find_state_button(container, state)

        button.click()
        self.quiesce()
        if element_visible(self.driver, '#transition_confirm_button'):
            self.driver.find_element_by_css_selector('#transition_confirm_button').click()
            self.quiesce()
        wait_for_transition(self.driver, self.standard_wait)

        try:
            self._find_state_button(container, state)
            raise RuntimeError("Transition to %s in %s failed (button still visible)" % (state, container))
        except NoSuchElementException:
            pass

    def get_table_text(self, table_element, columns):
        """Given a table element, return a list of lists of values
        of specified column indices"""

        records = []
        for row in table_element.find_elements_by_css_selector('tr'):
            tds = row.find_elements_by_css_selector('td')

            record = []
            try:
                for column_idx in columns:
                    record.append(tds[column_idx].text)
            except IndexError:
                continue

            records.append(record)

        return records

    def find_row_by_column_text(self, table, col_id_to_text):
        """Find a tr element within a table element which matches
        a map of column indices to column text"""

        rows = table.find_elements_by_css_selector("tr")
        for tr in rows:
            tds = tr.find_elements_by_css_selector("td")
            match = True
            for col_id, text in col_id_to_text.items():
                try:
                    if tds[col_id].text != text:
                        match = False
                except IndexError:
                    match = False
            if match:
                return tr

        raise RuntimeError("No match for %s in %s rows of table %s: %s" % (
            col_id_to_text, len(rows), table, self.get_table_text(table, col_id_to_text.keys())))

    def volume_chooser_open_and_select(self, chooser_id, server_address, volume_name, multi = False):
        """Click storage button and select an MGT from chooser"""
        chooser_button = self.driver.find_element_by_css_selector("#%s_outer" % chooser_id)
        chooser_button.click()
        self.volume_chooser_select(chooser_id, server_address, volume_name, multi)

    def volume_chooser_select(self, chooser_id, server_address, volume_name, multi):
        table = self.driver.find_element_by_css_selector("table#%s_table" % chooser_id)
        if multi:
            # Multi-selectable volume choosers have an extra column at 0 with a checkbox in
            row = self.find_row_by_column_text(table, {5: server_address, 1: volume_name})
        else:
            row = self.find_row_by_column_text(table, {4: server_address, 0: volume_name})
        row.click()

    def get_input_error(self, input_element):
        """Given an input element, get the validation error text attached to it, or
        raise an exception if it does not have a validation error"""

        parent = input_element.find_element_by_xpath("..")
        try:
            return parent.find_element_by_css_selector("span.error").text
        except NoSuchElementException:
            return None


class DatatableView(BaseView):
    datatable_id = None
    label_column = 0

    @property
    def datatable(self):
        return self.driver.find_element_by_css_selector("table#%s" % self.datatable_id)

    @property
    def rows(self):
        return self.driver.find_elements_by_xpath("id('" + self.datatable_id + "')/tbody/tr")

    def transition_by_column_values(self, column_values, state):
        table = self.driver.find_element_by_css_selector("#%s" % self.datatable_id)
        row = self.find_row_by_column_text(table, column_values)
        self.click_command_button(row, state)

    def remove_all(self):
        self.log.info("Removing %s rows in table #%s" % (len(self.rows), self.datatable_id))
        for tr in self.rows:
            tds = tr.find_elements_by_tag_name("td")
            if len(tds) == 1 and 'dataTables_empty' in tds[0].get_attribute('class').split():
                self.log.info("Table is empty")
                break

            label = tr.find_elements_by_tag_name("td")[self.label_column].text
            self.log.info("Removing object %s" % label)

            for button in tr.find_elements_by_tag_name("button"):
                if button.get_attribute('data-state') == 'removed':
                    button.click()
                    self.quiesce()
                    if element_visible(self.driver, '#transition_confirm_button'):
                        self.driver.find_element_by_css_selector('#transition_confirm_button').click()
                        self.quiesce()
                    wait_for_transition(self.driver, self.standard_wait)
                    break
