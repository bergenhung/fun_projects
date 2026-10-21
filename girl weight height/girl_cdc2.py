import pandas as pd
pd.options.mode.copy_on_write = True

import matplotlib.pyplot as plt
import numpy as np
import requests
from io import StringIO
from datetime import datetime

# URLs for CDC data
height_url = "https://www.cdc.gov/growthcharts/data/zscore/statage.csv"
weight_url = "https://www.cdc.gov/growthcharts/data/zscore/wtage.csv"

# Function to load and process data
def load_data(url):
    response = requests.get(url)
    data = StringIO(response.text)
    df = pd.read_csv(data)
    return df

# Load the datasets
height_df = load_data(height_url)
weight_df = load_data(weight_url)

# Filter for girls only (Sex = 2)
height_girls = height_df[height_df['Sex'] == 2]
weight_girls = weight_df[weight_df['Sex'] == 2]

# Convert Agemos (age in months) to years
height_girls['Age_Years'] = height_girls['Agemos'] / 12
weight_girls['Age_Years'] = weight_girls['Agemos'] / 12

# Filter for age range 6-12 years
height_girls = height_girls[(height_girls['Age_Years'] >= 6) & (height_girls['Age_Years'] <= 15)]
weight_girls = weight_girls[(weight_girls['Age_Years'] >= 6) & (weight_girls['Age_Years'] <= 15)]

# Sample data for the specific girl
sample_data = {
    'date': ['2022-05-26', '2023-06-01', '2024-04-22', '2025-04-22', '2025-12-01', '2026-04-18'],
    'age': [7.22, 8.24, 9.13, 10.13, 10.75, 11.25],
    'height': [124.7, 131.1, 136, 141.8, 145.5, 148.0],
    'weight': [23.5, 26.5, 27.8, 33.7, 36, 39.0]
}

# Convert to DataFrame
girl_df = pd.DataFrame(sample_data)

# Calculate exact age in years and months based on birthdate
birthdate = datetime.strptime('2015-03-05', '%Y-%m-%d')

# Function to calculate age in years and months
def calculate_exact_age(date_str):
    date = datetime.strptime(date_str, '%Y-%m-%d')
    years = date.year - birthdate.year
    months = date.month - birthdate.month
    if date.day < birthdate.day:
        months -= 1
    if months < 0:
        years -= 1
        months += 12
    return f"{years}y {months}m"

# Add formatted age to the DataFrame
girl_df['age_formatted'] = girl_df['date'].apply(calculate_exact_age)

# Create figure with two subplots
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

# Define percentiles and their corresponding columns
percentiles = [5, 10, 25, 50, 75, 90, 95]
percentile_cols = [f'L', f'M', f'S']
for p in percentiles:
    if p != 50:
        percentile_cols.append(f'P{p}')

# Colors for different percentiles
colors = plt.cm.viridis(np.linspace(0, 1, len(percentiles)))

# Plot height vs age
for i, p in enumerate(percentiles):
    if p == 50:
        # P50 is the M column (median)
        ax1.plot(height_girls['Age_Years'], height_girls['M'], 
                 label=f'P{p}', color=colors[i], linewidth=2.5)
    else:
        ax1.plot(height_girls['Age_Years'], height_girls[f'P{p}'], 
                 label=f'P{p}', color=colors[i], linewidth=1.5)

# Plot the Zoey's height measurements
ax1.scatter(girl_df['age'], girl_df['height'], color='red', s=100, marker='o', 
            edgecolor='black', zorder=5, label="Zoey's measurements")

# Annotate each measurement point with the age in years and months
for i, row in girl_df.iterrows():
    ax1.annotate(row['age_formatted'], 
                 xy=(row['age'], row['height']),
                 xytext=(10, 10),
                 textcoords='offset points',
                 fontsize=9,
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

ax1.set_title('Height vs Age for Girls (6-12 years)', fontsize=14)
ax1.set_xlabel('Age (years)', fontsize=12)
ax1.set_ylabel('Height (cm)', fontsize=12)
ax1.grid(True, alpha=0.3)
ax1.legend(title='Percentiles', loc='upper left')

# Plot weight vs age
for i, p in enumerate(percentiles):
    if p == 50:
        # P50 is the M column (median)
        ax2.plot(weight_girls['Age_Years'], weight_girls['M'], 
                 label=f'P{p}', color=colors[i], linewidth=2.5)
    else:
        ax2.plot(weight_girls['Age_Years'], weight_girls[f'P{p}'], 
                 label=f'P{p}', color=colors[i], linewidth=1.5)

# Plot the Zoey's weight measurements
ax2.scatter(girl_df['age'], girl_df['weight'], color='red', s=100, marker='o', 
            edgecolor='black', zorder=5, label="Zoey's measurements")

# Annotate each measurement point with the age in years and months
for i, row in girl_df.iterrows():
    ax2.annotate(row['age_formatted'], 
                 xy=(row['age'], row['weight']),
                 xytext=(10, 10),
                 textcoords='offset points',
                 fontsize=9,
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8))

ax2.set_title('Weight vs Age for Girls (6-12 years)', fontsize=14)
ax2.set_xlabel('Age (years)', fontsize=12)
ax2.set_ylabel('Weight (kg)', fontsize=12)
ax2.grid(True, alpha=0.3)
ax2.legend(title='Percentiles', loc='upper left')

# Function to calculate percentile for a given measurement
def calculate_percentile(age, measurement, reference_df, measurement_type):
    # Find the closest age in the reference data
    closest_age_row = reference_df.iloc[(reference_df['Age_Years'] - age).abs().argsort().iloc[0]]
    
    # Get the L, M, S parameters for that age
    L = closest_age_row['L']
    M = closest_age_row['M']
    S = closest_age_row['S']
    
    # Calculate z-score using the LMS method
    if L != 0:
        z = (((measurement / M) ** L) - 1) / (L * S)
    else:
        z = np.log(measurement / M) / S
    
    # Convert z-score to percentile
    percentile = 100 * (0.5 + 0.5 * np.tanh(0.5 * np.pi * z * np.sqrt(1/3)))
    
    return round(percentile, 1)

# Calculate percentiles for each measurement
height_percentiles = []
weight_percentiles = []

for i, row in girl_df.iterrows():
    height_pct = calculate_percentile(row['age'], row['height'], height_girls, 'height')
    weight_pct = calculate_percentile(row['age'], row['weight'], weight_girls, 'weight')
    height_percentiles.append(height_pct)
    weight_percentiles.append(weight_pct)

girl_df['height_percentile'] = height_percentiles
girl_df['weight_percentile'] = weight_percentiles

# Add a table with the data to the figure
plt.figtext(0.5, 0.01, 'Measurement Data', ha='center', fontsize=14, fontweight='bold')
table_data = [
    ['Date', 'Age', 'Height', 'H-%ile', 'Weight', 'W-%ile']
]

for i, row in girl_df.iterrows():
    table_data.append([
        row['date'], 
        row['age_formatted'], 
        str(row['height']), 
        str(row['height_percentile']), 
        str(row['weight']),
        str(row['weight_percentile'])
    ])

table = plt.table(
    cellText=table_data,
    colWidths=[0.12, 0.08, 0.1, 0.1, 0.1, 0.1],
    loc='bottom',
    bbox=[0.15, -0.35, 0.7, 0.25]
)
table.auto_fit = True
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1, 1.5)

for i in range(len(table_data)):
    for j in range(len(table_data[0])):
        cell = table[i, j]
        if i == 0:  # Header row
            cell.set_text_props(weight='bold', color='white')
            cell.set_facecolor('#4472C4')
        elif i % 2 == 1:  # Alternate row colors
            cell.set_facecolor('#D9E1F2')
        else:
            cell.set_facecolor('#EDEDED')

plt.tight_layout()
plt.subplots_adjust(bottom=0.35)  # Make room for the table
plt.savefig('cdc_growth_charts_girls.png', dpi=300, bbox_inches='tight')
plt.show()

print("Analysis complete! The growth charts show:")
print("1. CDC reference percentiles (5th, 10th, 25th, 50th, 75th, 90th, and 95th) for girls aged 6-12 years")
print("2. The individual Zoey's measurements plotted as red dots")
print("3. Age labels in years and months format (e.g., '7y 2m')")
print("4. A table showing the exact measurements and calculated percentiles for each data point")