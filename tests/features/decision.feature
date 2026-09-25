Feature: A synthetic event becomes a safe, inspectable decision

  Scenario: Sustained CPU and service errors produce one alert
    Given synthetic CPU is high for six minutes and service errors are elevated
    And Jev chooses alert
    When Perry processes the event
    Then the recorded decision is alert
    And the notification receiver is called once

  Scenario: Maintenance must not notify
    Given a sustained synthetic problem during maintenance
    And Jev chooses alert
    When Perry processes the event
    Then the recorded decision is suppressed
    And the notification receiver is never called
