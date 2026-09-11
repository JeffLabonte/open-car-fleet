Feature: Garage sharing lifecycle
  Fleet owners and admins can invite collaborators, manage their roles,
  and revoke access. Viewers can only read shared fleet data.

  Background:
    Given a running application server
    And a fleet owner "owner@example.com"
    And a fleet "Shared Fleet" owned by "owner@example.com"

  Scenario: Owner invites a viewer by email
    Given "owner@example.com" is signed in
    When they visit the share page for "Shared Fleet"
    And they invite "viewer@example.com" with role "Viewer"
    Then a pending invitation exists for "viewer@example.com"
    And the invitation role is "Viewer"

  Scenario: Viewer cannot invite others
    Given "viewer@example.com" is a viewer of "Shared Fleet"
    And "viewer@example.com" is signed in
    When they visit the share page for "Shared Fleet"
    Then they are redirected away without accessing member management

  Scenario: Viewer can view fleet cars but not add cars
    Given "viewer@example.com" is a viewer of "Shared Fleet"
    And a car "Daily Driver" exists in "Shared Fleet"
    And "viewer@example.com" is signed in
    When they visit the fleet detail page for "Shared Fleet"
    Then they see "Daily Driver"
    And they do not see an "Add car" button

  Scenario: Admin can change a member role
    Given "admin@example.com" is an admin of "Shared Fleet"
    And "viewer@example.com" is a viewer of "Shared Fleet"
    And "admin@example.com" is signed in
    When they change the role of "viewer@example.com" to "Mechanic"
    Then "viewer@example.com" has role "Mechanic" in "Shared Fleet"

  Scenario: Admin cannot promote a viewer to Owner
    Given "admin@example.com" is an admin of "Shared Fleet"
    And "viewer@example.com" is a viewer of "Shared Fleet"
    And "admin@example.com" is signed in
    When they attempt to change the role of "viewer@example.com" to "Owner"
    Then "viewer@example.com" still has role "Viewer" in "Shared Fleet"

  Scenario: Owner removes a member
    Given "viewer@example.com" is a viewer of "Shared Fleet"
    And "owner@example.com" is signed in
    When they remove "viewer@example.com" from "Shared Fleet"
    Then "viewer@example.com" is no longer a member of "Shared Fleet"

  Scenario: Stranger cannot access another fleet
    Given a user "stranger@example.com"
    And "stranger@example.com" is signed in
    When they visit the fleet detail page for "Shared Fleet"
    Then they see a not found page
