import gradio as gr
import pandas as pd
from datetime import datetime, date, timedelta
import os
import time

# --- Configuration ---
PROJECTS_FILE = "projects.txt"
LOG_FILE = "work_log.csv"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
DATETIME_COL = "Timestamp_dt" # For internal calculations
# Define columns expected in the raw log file
RAW_LOG_COLS = ["Timestamp", "Project", "Activity", "Type"]
# Define columns for the final display DataFrame
DISPLAY_COLUMNS = ["Timestamp", "Project", "Activity", "Type", "Duration (HH:MM:SS)"] # Changed duration column

# --- Helper Functions ---

def parse_datetime(timestamp_str):
    """Safely parse timestamp string to datetime object."""
    try:
        return datetime.strptime(timestamp_str, DATE_FORMAT)
    except (ValueError, TypeError):
        return pd.NaT

def format_seconds_to_hms(total_seconds):
    """Formats total seconds into HH:MM:SS string."""
    if pd.isna(total_seconds) or total_seconds < 0:
        return "" # Return empty for invalid or NA durations
    total_seconds_int = int(total_seconds)
    hours = total_seconds_int // 3600
    minutes = (total_seconds_int % 3600) // 60
    seconds = total_seconds_int % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def get_current_time_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# --- Project Persistence ---

def load_projects():
    """Loads project names from the projects file."""
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with open(PROJECTS_FILE, 'r') as f:
            projects = [line.strip() for line in f if line.strip()]
        return sorted(list(set(projects)))
    except Exception as e:
        print(f"Error loading projects file: {e}")
        return []

def save_projects(projects_list):
    """Saves the list of projects to the projects file."""
    try:
        unique_sorted_projects = sorted(list(set(p.strip() for p in projects_list if p.strip())))
        with open(PROJECTS_FILE, 'w') as f:
            for project in unique_sorted_projects:
                f.write(project + '\n')
    except Exception as e:
        print(f"Error saving projects file: {e}")

# --- Log Data Handling & Duration Calculation ---

def load_log():
    """Loads the RAW log data from the CSV file without duration processing."""
    if os.path.exists(LOG_FILE):
        try:
            df = pd.read_csv(LOG_FILE, dtype=str) # Read all as string initially
            if df.empty:
                 return pd.DataFrame(columns=RAW_LOG_COLS)
            # Ensure all expected columns exist, add if missing with NA (as string)
            for col in RAW_LOG_COLS:
                if col not in df.columns:
                    df[col] = "" # Use empty string for missing str columns
            return df[RAW_LOG_COLS] # Return only expected columns
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=RAW_LOG_COLS)
        except Exception as e:
            print(f"Error loading raw log file: {e}")
            return pd.DataFrame(columns=RAW_LOG_COLS)
    else:
        # Create file with headers if it doesn't exist
        df = pd.DataFrame(columns=RAW_LOG_COLS)
        df.to_csv(LOG_FILE, index=False)
        return df


def calculate_durations_seconds(df):
    """Adds 'Duration_sec' column based on time difference to next event."""
    if df.empty:
        return df.assign(Duration_sec=pd.NA) # Add empty column

    # Ensure timestamp column exists and parse dates
    if 'Timestamp' not in df.columns:
         print("Warning: Timestamp column missing for duration calculation.")
         return df.assign(Duration_sec=pd.NA)
    df[DATETIME_COL] = df['Timestamp'].apply(parse_datetime)

    # IMPORTANT: Drop rows where timestamp parsing failed BEFORE calculating diffs
    df = df.dropna(subset=[DATETIME_COL]).sort_values(by=DATETIME_COL)

    # Check if empty again after dropping NaTs
    if df.empty:
        return df.assign(Duration_sec=pd.NA)

    # Calculate duration based on the time difference to the *next* row's timestamp
    df['Time_Diff_Next'] = df[DATETIME_COL].diff().shift(-1) # Time diff with the *next* log entry

    # Store total seconds as float, coerce errors
    df['Duration_sec'] = pd.to_numeric(df['Time_Diff_Next'].dt.total_seconds(), errors='coerce')

    # Clean up temporary columns if they exist
    if 'Time_Diff_Next' in df.columns:
        df = df.drop(columns=['Time_Diff_Next'])
    # Keep DATETIME_COL for sorting in the next step

    return df


def load_and_process_log():
    """Loads log, calculates durations (sec), formats for display (HH:MM:SS)."""
    try:
        df_raw = load_log()
        if df_raw.empty:
            return pd.DataFrame(columns=DISPLAY_COLUMNS)

        # Calculate durations in seconds
        df_processed = calculate_durations_seconds(df_raw.copy()) # Gets df with Duration_sec

        # Format the duration seconds into HH:MM:SS string for display
        if 'Duration_sec' in df_processed.columns:
            df_processed['Duration (HH:MM:SS)'] = df_processed['Duration_sec'].apply(format_seconds_to_hms)
        else: # Handle case where column might not exist if processing failed
            df_processed['Duration (HH:MM:SS)'] = ""

        # Select and order columns for display, sort by original datetime col
        if DATETIME_COL in df_processed.columns:
             display_df = df_processed.sort_values(by=DATETIME_COL, ascending=False)
        else: # Fallback sort by string timestamp if datetime failed everywhere
             display_df = df_processed.sort_values(by='Timestamp', ascending=False)


        # Ensure all expected DISPLAY_COLUMNS exist before returning
        for col in DISPLAY_COLUMNS:
            if col not in display_df.columns:
                display_df[col] = "" # Add missing display columns

        return display_df[DISPLAY_COLUMNS] # Return only display columns

    except Exception as e:
        print(f"Error loading or processing log file: {e}")
        return pd.DataFrame(columns=DISPLAY_COLUMNS) # Return empty on error


def calculate_total_hours_today():
    """Calculates total work duration logged for today (HH:MM:SS)."""
    total_seconds_today = 0
    try:
        raw_log_df = load_log() # Load raw data
        if raw_log_df.empty:
            return "00:00:00"

        # Process timestamps and sort
        raw_log_df[DATETIME_COL] = raw_log_df['Timestamp'].apply(parse_datetime)
        raw_log_df = raw_log_df.dropna(subset=[DATETIME_COL]).sort_values(by=DATETIME_COL)
        if raw_log_df.empty:
            return "00:00:00"

        # --- Calculate durations for completed intervals today ---
        # Calculate time differences between consecutive rows
        raw_log_df['Time_Diff_Next'] = raw_log_df[DATETIME_COL].diff().shift(-1)
        # Calculate duration in seconds from the difference
        raw_log_df['Duration_sec_calc'] = pd.to_numeric(raw_log_df['Time_Diff_Next'].dt.total_seconds(), errors='coerce')

        today_date = date.today()
        # Filter for 'Start' entries that STARTED today and have a calculated duration
        # (meaning there was a subsequent event logged)
        today_completed_entries = raw_log_df[
            (raw_log_df[DATETIME_COL].dt.date == today_date) &
            (raw_log_df['Type'] == 'Start') &
            (raw_log_df['Duration_sec_calc'].notna()) &
            (raw_log_df['Duration_sec_calc'] >= 0) # Ensure duration is non-negative
        ]
        # Sum the calculated durations in seconds
        total_seconds_from_completed = today_completed_entries['Duration_sec_calc'].sum()
        if not pd.isna(total_seconds_from_completed):
             total_seconds_today += total_seconds_from_completed

        # --- Check for ongoing task ---
        last_entry = raw_log_df.iloc[-1]
        # If the very last entry was a 'Start' today, calculate time until now
        if last_entry['Type'] == 'Start' and last_entry[DATETIME_COL].date() == today_date:
            duration_ongoing = datetime.now() - last_entry[DATETIME_COL]
            total_seconds_today += duration_ongoing.total_seconds()

        # --- Format Output ---
        if pd.isna(total_seconds_today):
            total_seconds_today = 0

        return format_seconds_to_hms(total_seconds_today) # Use helper to format

    except Exception as e:
        # Added more specific error context
        print(f"Error in calculate_total_hours_today: {e}")
        # Print DataFrame state if useful for debugging
        # print("DataFrame state in calculate_total_hours_today:\n", raw_log_df.head())
        return "Error"

# --- Action Functions (add_project_action, remove_project_action, log_event) ---
# These functions remain largely the same, ensuring they interact correctly
# with project state and trigger updates. `log_event` still triggers updates
# for log_display_df and total_hours_display.

def add_project_action(new_project_name, current_projects_in_state):
    # (Code is the same as before)
    updated_projects = list(current_projects_in_state)
    if not new_project_name:
        gr.Warning("Project name cannot be empty.")
        return gr.update(choices=updated_projects), "", updated_projects
    new_project_name = new_project_name.strip()
    if any(new_project_name.lower() == proj.lower() for proj in updated_projects):
        gr.Info(f"Project '{new_project_name}' already exists.")
        return gr.update(choices=updated_projects), "", updated_projects
    else:
        updated_projects.append(new_project_name)
        updated_projects = sorted(updated_projects)
        save_projects(updated_projects)
        gr.Info(f"Project '{new_project_name}' added.")
        return gr.update(choices=updated_projects), "", updated_projects

def remove_project_action(project_to_remove, current_projects_in_state):
    # (Code is the same as before)
    updated_projects = list(current_projects_in_state)
    if not project_to_remove:
        gr.Warning("Please select a project to remove.")
        return gr.update(choices=updated_projects, value=None), updated_projects
    project_to_remove_stripped = project_to_remove.strip()
    found_project = None
    for proj in updated_projects:
        if proj.lower() == project_to_remove_stripped.lower():
            found_project = proj
            break
    if found_project:
        updated_projects.remove(found_project)
        save_projects(updated_projects)
        gr.Info(f"Project '{found_project}' removed.")
        return gr.update(choices=updated_projects, value=None), updated_projects
    else:
        gr.Warning(f"Project '{project_to_remove}' not found.")
        return gr.update(choices=updated_projects, value=project_to_remove), updated_projects



def get_button_states(selected_project):
    """Determines interactive state for Remove, Start, Stop buttons.
    Returns: (remove_update, start_update, stop_update)
    """
    # --- Determine state based on project selection ---
    project_is_selected = bool(selected_project and selected_project.strip())
    remove_btn_state = gr.update(interactive=project_is_selected)

    # --- Determine Start/Stop state based on selection AND last log entry ---
    start_btn_state = gr.update(interactive=False) # Default to disabled
    stop_btn_state = gr.update(interactive=False)  # Default to disabled

    if project_is_selected:
        # Find last log entry type only if a project is selected
        last_entry_type = None
        try: # Add error handling for log loading/parsing
            raw_log = load_log()
            if not raw_log.empty:
                raw_log[DATETIME_COL] = raw_log['Timestamp'].apply(parse_datetime)
                valid_log = raw_log.dropna(subset=[DATETIME_COL]).sort_values(by=DATETIME_COL)
                if not valid_log.empty:
                    last_entry_type = valid_log.iloc[-1].get('Type')
        except Exception as e:
            print(f"Error reading log state for button update: {e}")
            # Keep buttons disabled if log reading fails

        # Enable Start/Stop based on last type
        if last_entry_type == 'Start':
            # Task running -> Can Stop, Cannot Start
            start_btn_state = gr.update(interactive=False)
            stop_btn_state = gr.update(interactive=True)
        else: # last_entry_type is 'Stop' or None (empty/invalid log)
            # No task running -> Can Start, Cannot Stop
            start_btn_state = gr.update(interactive=True)
            stop_btn_state = gr.update(interactive=False)

    return remove_btn_state, start_btn_state, stop_btn_state


def log_event(project, activity, event_type, current_projects_in_state):
    """Logs event, prevents invalid actions (concurrent Starts, wrong Stops), returns updates."""
    updated_project_list = list(current_projects_in_state)
    # Get current button states for potential abort returns
    current_remove_btn, current_start_btn, current_stop_btn = get_button_states(project)

    # --- Get Last Log State ---
    last_entry_type = None
    last_entry_project = None # Store the project name from the last entry
    running_project_info = "Unknown Task"
    try:
        raw_log = load_log()
        if not raw_log.empty:
            raw_log[DATETIME_COL] = raw_log['Timestamp'].apply(parse_datetime)
            valid_log = raw_log.dropna(subset=[DATETIME_COL]).sort_values(by=DATETIME_COL)
            if not valid_log.empty:
                last_entry = valid_log.iloc[-1]
                last_entry_type = last_entry.get('Type')
                last_entry_project = last_entry.get('Project') # Get the project from the last valid entry
                # Create info string for warnings
                running_project = last_entry_project if last_entry_project else 'Unknown'
                running_activity = last_entry.get('Activity', '')
                running_project_info = f"'{running_project}{' - ' + running_activity if running_activity else ''}'"
    except Exception as e:
        print(f"Error reading log state in log_event check: {e}")
        # If log reading fails, maybe best to prevent actions? Or allow cautiously?
        # Let's prevent for safety, returning current state
        gr.Error("Error reading log file state. Cannot proceed.")
        return (load_and_process_log(), activity, gr.update(choices=updated_project_list),
                updated_project_list, calculate_total_hours_today(),
                current_start_btn, current_stop_btn)

    # --- Apply Rules ---
    if event_type == 'Start':
        if last_entry_type == 'Start':
            gr.Warning(f"Cannot start: Task {running_project_info} is already running. Please Stop it first.")
            # Return current state (7 values)
            return (load_and_process_log(), activity, gr.update(choices=updated_project_list),
                    updated_project_list, calculate_total_hours_today(),
                    current_start_btn, current_stop_btn)

    elif event_type == 'Stop':
        # --- Refined Stop Check ---
        # 1. Check if anything is running at all
        if last_entry_type != 'Start':
            warning_msg = "No task currently running (last entry was not 'Start'). Cannot Stop."
            if last_entry_type is None:
                 warning_msg = "Log is empty or has no valid entries. Nothing to stop."
            gr.Warning(warning_msg)
            # Return current state (7 values)
            return (load_and_process_log(), activity, gr.update(choices=updated_project_list),
                    updated_project_list, calculate_total_hours_today(),
                    current_start_btn, current_stop_btn)

        # 2. Check if selected project MATCHES the running project
        selected_project_clean = project.strip().lower() if project else ""
        last_entry_project_clean = last_entry_project.strip().lower() if last_entry_project else ""

        if selected_project_clean != last_entry_project_clean:
            gr.Warning(f"Cannot stop '{project}'. The currently running project is '{last_entry_project}'. Please select '{last_entry_project}' to stop it.")
            # Return current state (7 values)
            return (load_and_process_log(), activity, gr.update(choices=updated_project_list),
                    updated_project_list, calculate_total_hours_today(),
                    current_start_btn, current_stop_btn)
        # If we reach here, last entry was 'Start' AND projects match. Allow Stop.

    # --- Proceed with Logging if Checks Passed ---
    # Basic project selection validation (redundant if using get_button_states logic but safe)
    if not project:
        gr.Warning(f"Please select a project to {event_type.lower()}.")
        # Return current state (7 values)
        return (load_and_process_log(), activity, gr.update(choices=updated_project_list),
                updated_project_list, calculate_total_hours_today(),
                current_start_btn, current_stop_btn)

    # (Prepare log entry - same as before)
    project = project.strip()
    activity = activity.strip() if activity else ""
    if event_type == 'Start' and not activity: activity = "Starting work"
    elif event_type == 'Stop' and not activity: activity = "Stopping work" # Default Stop message
    # Update project list if needed (e.g., typed-in value was used for start/stop)
    if not any(project.lower() == p.lower() for p in updated_project_list):
         updated_project_list.append(project)
         updated_project_list = sorted(updated_project_list)
         save_projects(updated_project_list) # Save if a new one was somehow used

    now = datetime.now()
    timestamp_str = now.strftime(DATE_FORMAT)
    new_entry = pd.DataFrame([{"Timestamp": timestamp_str, "Project": project, "Activity": activity, "Type": event_type}])

    # --- Attempt Logging and Return NEW State ---
    try:
        file_exists = os.path.exists(LOG_FILE)
        new_entry[RAW_LOG_COLS].to_csv(LOG_FILE, mode='a', header=not file_exists or os.path.getsize(LOG_FILE) == 0, index=False)
        gr.Info(f"{event_type} logged for: {project}")

        # Calculate NEW button states AFTER successful logging based on the *new* last state
        _ , new_start_btn, new_stop_btn = get_button_states(project)

        processed_log = load_and_process_log()
        total_hours = calculate_total_hours_today()
        # Return new state (7 values)
        return (processed_log, "", gr.update(choices=updated_project_list),
                updated_project_list, total_hours,
                new_start_btn, new_stop_btn)

    except Exception as e:
        gr.Error(f"Failed to write log: {e}")
        # Return state before failed attempt (7 values)
        processed_log = load_and_process_log()
        total_hours = calculate_total_hours_today()
        return (processed_log, activity, gr.update(choices=updated_project_list),
                updated_project_list, total_hours,
                current_start_btn, current_stop_btn) # Return original button states


# --- Gradio Interface ---

with gr.Blocks(theme=gr.themes.Soft(), title="HoraLog") as app:
    # --- Initial Data Loading & State ---
    # Load projects for dropdown and state management
    initial_project_list = load_projects()
    project_choices_state = gr.State(initial_project_list)
    # Note: Initial log data for the DataFrame is loaded via its 'value' function below

    # --- UI Layout ---
    gr.Markdown("# HoraLog - Time Tracker")

    # Row 1: Clocks
    with gr.Row():
        current_time_display = gr.Textbox(
            label="Current Time",
            value=get_current_time_str, # Function for live update
            interactive=False,
            every=1 # Update every second
        )
        total_hours_display = gr.Textbox(
            label="Total Hours Today (HH:MM:SS)",
            value=calculate_total_hours_today, # Function for live update
            interactive=False,
            every=1 # Update every second (can adjust if performance is an issue)
        )

    # Row 2: Project Management
    gr.Markdown("## Manage Projects")
    with gr.Row():
         project_name_textbox = gr.Textbox(
             label="Project Name",
             placeholder="Enter project name to add" # Clearer placeholder
         )
         add_project_button = gr.Button(
             "Add Project",
             interactive=False # Start disabled until text is entered
             )
         remove_project_button = gr.Button(
             "Remove Selected",
             interactive=False # Start disabled until project is selected
             )

    # Row 3 & 4: Logging Actions
    gr.Markdown("## Log Work")
    with gr.Row():
        project_dropdown = gr.Dropdown(
            label="Project",
            choices=initial_project_list, # Initial list loaded from file
            value=None, # Start with no project selected
            allow_custom_value=True, # Allows typing new projects directly
            elem_id="project-dropdown"
        )
    with gr.Row():
         activity_textbox = gr.Textbox(
             label="Activity Description (Optional)",
             placeholder="What are you working on?",
             lines=2,
             elem_id="activity-input"
        )
    with gr.Row():
        start_button = gr.Button(
            "Start Work",
            variant="primary",
            interactive=False # Start disabled until project selected & task not running
            )
        stop_button = gr.Button(
            "Stop Work",
            variant="stop", # Specific variant for stop potentially
            interactive=False # Start disabled until project selected & task is running
            )

    # Separator and History Section
    gr.Markdown("---")
    gr.Markdown("## Activity Log History")

    # Row 5: Refresh Button
    with gr.Row():
        refresh_log_button = gr.Button("🔄 Refresh Log History")

    # Row 6: Log DataFrame Display
    log_display_df = gr.DataFrame(
        value=load_and_process_log, # Use function for initial/refresh load
        label="Log Entries",
        interactive=False,
        row_count=(15, "dynamic"), # Rows to display, with scroll/pagination
        col_count=(len(DISPLAY_COLUMNS), "fixed"), # Ensure correct number of columns
        headers=DISPLAY_COLUMNS, # Defined list: ["Timestamp", "Project", ..., "Duration (HH:MM:SS)"]
        datatype=['str', 'str', 'str', 'str', 'str'], # All displayed as strings now
        # height=500 # Optional: Uncomment to set fixed height
    )

    # --- Event Handling Logic ---

    # 1. Enable/Disable "Add Project" button based on text input
    def update_add_button_state(text):
        """Enable Add button only if text is entered."""
        return gr.update(interactive=bool(text and text.strip()))
    project_name_textbox.change(
        fn=update_add_button_state,
        inputs=project_name_textbox,
        outputs=add_project_button
        )

    # 2. Update "Remove", "Start", "Stop" buttons when project selection changes
    project_dropdown.change(
        fn=get_button_states, # Central function to determine button interactivity
        inputs=project_dropdown,
        outputs=[remove_project_button, start_button, stop_button]
        )

    # 3. "Add Project" button action
    add_project_button.click(
        fn=add_project_action,
        inputs=[project_name_textbox, project_choices_state],
        # Outputs: Update dropdown choices, clear textbox, update internal state
        outputs=[project_dropdown, project_name_textbox, project_choices_state]
        )

    # 4. "Remove Selected" button action
    remove_project_button.click(
        fn=remove_project_action,
        inputs=[project_dropdown, project_choices_state],
        # Outputs: Update dropdown choices/value, update internal state
        outputs=[project_dropdown, project_choices_state]
        )

    # 5. "Refresh Log History" button action
    refresh_log_button.click(
        fn=load_and_process_log, # Function to reload data from CSV
        inputs=None,              # No inputs needed for refresh
        outputs=[log_display_df]  # Target the DataFrame for update
        )

    # 6. "Start Work" button action
    start_button.click(
        fn=log_event,
        # Inputs: Selected project, activity text, hidden 'Start' type, project list state
        inputs=[project_dropdown, activity_textbox, gr.Textbox(value="Start", visible=False), project_choices_state],
        # Outputs: Update log DF, clear activity, update dropdown, update state, update total hours, update start btn state, update stop btn state
        outputs=[
            log_display_df,
            activity_textbox,
            project_dropdown,
            project_choices_state,
            total_hours_display,
            start_button,
            stop_button
        ]
    )

    # 7. "Stop Work" button action
    stop_button.click(
        fn=log_event,
         # Inputs: Selected project, activity text, hidden 'Stop' type, project list state
        inputs=[project_dropdown, activity_textbox, gr.Textbox(value="Stop", visible=False), project_choices_state],
         # Outputs: Update log DF, clear activity, update dropdown, update state, update total hours, update start btn state, update stop btn state
        outputs=[
            log_display_df,
            activity_textbox,
            project_dropdown,
            project_choices_state,
            total_hours_display,
            start_button,
            stop_button
        ]
    )

# --- Run the App ---
if __name__ == "__main__":
    if not os.path.exists(PROJECTS_FILE):
        open(PROJECTS_FILE, 'a').close()
    if not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0:
         pd.DataFrame(columns=RAW_LOG_COLS).to_csv(LOG_FILE, index=False)

    app.launch(server_name="0.0.0.0", server_port=7860)