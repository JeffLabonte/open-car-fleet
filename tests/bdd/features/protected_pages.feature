Feature: Protected application pages
  Anonymous users must be sent to the authentication page before viewing fleet data.

  Scenario: Anonymous user visits the car list
    Given an anonymous test client
    When the client requests the car list
    Then the response redirects to the login page
