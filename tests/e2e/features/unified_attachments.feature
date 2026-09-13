Feature: Unified attachment mechanism
  Every create form exposes a single attachment upload component at the
  bottom, accepting photos, videos, and documents. Uploaded attachments are
  stored once, rendered everywhere through one serving view, and rejected
  when their type or content is unsafe.

  Background:
    Given a running application server

  Scenario: The attachment component is the last field of the report form
    Given "owner@example.com" is signed in
    And a fleet "Bottom Fleet" owned by "owner@example.com"
    And a car "Bottom Check" exists in "Bottom Fleet"
    When they open the maintenance report form for the current car
    Then the attachment upload section is the last form field
    And the external links field renders before the attachment section

  Scenario: A report can be created with an uploaded photo attachment
    Given "owner@example.com" is signed in
    And a fleet "Photo Fleet" owned by "owner@example.com"
    And a car "Photo Check" exists in "Photo Fleet"
    When they open the maintenance report form for the current car
    And they fill the report with job "Brake service with photo"
    And they attach the photo file to the report form
    And they submit the report form
    Then the car detail page lists the attachment

  Scenario: A report can be created with external links only
    Given "owner@example.com" is signed in
    And a fleet "Links Fleet" owned by "owner@example.com"
    And a car "Links Check" exists in "Links Fleet"
    When they open the maintenance report form for the current car
    And they fill the report with job "Brake service with links"
    And they add the external link to the report form
    And they submit the report form
    Then the car detail page lists the external link

  Scenario: An unsafe attachment is rejected with a validation error
    Given "owner@example.com" is signed in
    And a fleet "Invalid Fleet" owned by "owner@example.com"
    And a car "Invalid Check" exists in "Invalid Fleet"
    When they open the maintenance report form for the current car
    And they fill the report with job "Unsafe upload attempt"
    And they attach the unsafe file to the report form
    And they submit the report form
    Then an attachment validation error is displayed
    And the browser stays on the report form

  Scenario: A car document can be created with a PDF attachment
    Given "owner@example.com" is signed in
    And a fleet "Docs Fleet" owned by "owner@example.com"
    And a car "Docs Check" exists in "Docs Fleet"
    When they create a car document titled "Owner manual"
    And they attach the pdf file to the car document form
    And they submit the car document form
    Then the car document list shows the attachment

  Scenario: A known shop proof can be created with a PDF attachment
    Given "owner@example.com" is signed in
    When they create a known shop named "Proofed Garage"
    And they open the add proof form for that shop
    And they fill the proof with title "Business registration"
    And they attach the pdf file to the proof form
    And they submit the proof form
    Then the shop detail page lists the proof attachment
