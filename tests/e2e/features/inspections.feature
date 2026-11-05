Feature: Vehicle inspection history
  Vehicle inspections keep their exact inspection time, evidence, and recommended work.
  The vehicle page shows only the latest inspection while the history page shows all inspections.

  Scenario: Creating an inspection starts as a detailed draft with clear actions
    Given a running application server for inspections
    And an inspection owner "inspection-e2e@example.com" is signed in
    And an inspection fleet "Inspection Fleet" exists
    And an inspection car "Inspection Vehicle" exists
    When they start an inspection at "2026-10-20T14:30" with notes "DRAFT_FINDINGS"
    Then the inspection form shows the save draft and finalize buttons
    And the detailed checklist is visible with fluids and filters items

  Scenario: Finalizing an inspection saves it and returns to the car page
    Given a running application server for inspections
    And an inspection owner "inspection-e2e@example.com" is signed in
    And an inspection fleet "Inspection Fleet" exists
    And an inspection car "Inspection Vehicle" exists
    When they start an inspection at "2026-10-20T14:30" with notes "FINALIZED_FINDINGS"
    And they finalize the inspection
    Then the vehicle page shows the finalized inspection

  Scenario: Select all and deselect all sections toggles the checklist
    Given a running application server for inspections
    And an inspection owner "inspection-e2e@example.com" is signed in
    And an inspection fleet "Inspection Fleet" exists
    And an inspection car "Inspection Vehicle" exists
    When they start an inspection at "2026-10-20T14:30" with notes "TOGGLE_FINDINGS"
    And they deselect all checklist sections
    Then all checklist sections are disabled
    When they select all checklist sections
    Then all checklist sections are enabled

  Scenario: Latest inspection and recommended work are visible with history available
    Given a running application server for inspections
    And an inspection owner "inspection-e2e@example.com" is signed in
    And an inspection fleet "Inspection Fleet" exists
    And an inspection car "Inspection Vehicle" exists
    When they start an inspection at "2026-10-01T09:00" with notes "OLDER_INSPECTION_FINDINGS"
    And they finalize the inspection
    And they start an inspection at "2026-10-20T14:30" with notes "LATEST_INSPECTION_FINDINGS"
    And they attach an inspection photo and document
    Then the vehicle page shows only the latest inspection
    And the vehicle page shows the inspection evidence
    When they open the inspection history
    Then the inspection history shows both inspections
    And the inspection history shows the inspection evidence
    When they add recommended work "Replace brake pads" planned for "2026-11-01"
    Then the latest inspection shows the recommended work
