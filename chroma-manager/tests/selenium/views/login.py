from urlparse import urlunparse

from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import StaleElementReferenceException
from tests.selenium.base_view import BaseView
from tests.selenium.views.eula import Eula


class Login(BaseView):
    path = BaseView.path + "login/"

    @property
    def container(self):
        return self.driver.find_element_by_class_name("login-partial")

    @property
    def username(self):
        return self.container.find_element_by_css_selector("input[name=username]")

    @property
    def password(self):
        return self.container.find_element_by_css_selector("input[name=password]")

    @property
    def login_button(self):
        return self.container.find_element_by_class_name("btn-success")

    @property
    def logout_button(self):
        return self.driver.find_element_by_class_name("logout")

    def go_to_page(self):
        """
        Loads the login page if we are not already there.
        @return: This instance
        """

        if not self.on_page():
            parts = self._get_url_parts()
            parts[2] = self.path
            self.driver.get(urlunparse(parts))
            self._reset_ui(True)

        return self

    def login_and_accept_eula_if_presented(self, username, password, must_accept=False):
        """
        Logs the user in and accepts the eula if on appears.
        @param username: The username
        @param password: The password
        @param must_accept: If true an error will be raised if the eula modal does not appear or the page does
               not change.
        @return: This instance.
        """
        self.login(username, password)
        Eula(self.driver).accept(must_accept)

        # After refresh we should see the username field.
        WebDriverWait(self.driver, self.short_wait).until(lambda driver: driver.find_element_by_id("account"))

        # Page should be reloaded, make sure it is usable.
        self._reset_ui(angular_only=True)

        return self

    def login_and_reject_eula(self, username, password):
        """
        Logs the user in and rejects the eula.
        @param username: The username
        @param password: The password
        @return: This instance
        """
        self.login(username, password)
        Eula(self.driver).reject()

        def wait_for_refresh(login):
            try:
                return login.username.get_attribute("value") == username
            except StaleElementReferenceException:
                return False

        # Login username field should be empty on a refresh and not before.
        WebDriverWait(self, self.short_wait).until(wait_for_refresh)

        # Page should be reloaded, make sure it is usable.
        self._reset_ui(True)

    def login(self, username, password):
        """
        Logs the user in
        @param username: The username
        @param password: The password
        @return: This instance
        """
        self.log.debug("Logging in %s" % username)
        self.wait_for_angular()
        self.username.send_keys(username)
        self.password.send_keys(password)
        self.login_button.click()

        return self

    def logout(self):
        """
        Logs out the user.
        @return: This instance
        """
        self.log.debug("Logging out")
        self.logout_button.click()

        def wait_on_username(login):
            try:
                return login.username.get_attribute("value") == ""
            except StaleElementReferenceException:
                return False

        WebDriverWait(self, self.short_wait).until(wait_on_username,
                                                   "Login screen still not visible after %s seconds" % self.short_wait)

        # Page should be reloaded, make sure it is usable.
        self._reset_ui(True)

        return self