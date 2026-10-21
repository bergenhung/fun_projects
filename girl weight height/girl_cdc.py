import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import matplotlib.patches as mpatches

class CDCGrowthChartPlotter:
    def __init__(self):
        # CDC data for girls 6-12 years (height in cm)
        self.cdc_height_data = {
            "age": [6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0],
            "p5": [106.5, 109.5, 112.2, 115.0, 117.8, 120.6, 123.5, 126.3, 129.2, 132.2, 135.5, 138.8, 142.2],
            "p10": [108.4, 111.3, 114.1, 117.0, 120.0, 122.9, 125.9, 128.8, 131.7, 134.9, 138.3, 141.8, 145.2],
            "p25": [111.4, 114.4, 117.3, 120.3, 123.5, 126.6, 129.7, 132.8, 136.0, 139.4, 143.1, 146.7, 150.5],
            "p50": [115.1, 118.2, 121.1, 124.3, 127.6, 130.9, 134.2, 137.5, 140.9, 144.5, 148.7, 152.7, 156.5],
            "p75": [118.7, 121.9, 124.9, 128.1, 131.5, 134.9, 138.3, 141.8, 145.5, 149.4, 153.6, 157.7, 161.6],
            "p90": [121.7, 125.0, 128.2, 131.5, 134.9, 138.4, 142.0, 145.7, 149.5, 153.5, 157.8, 162.0, 166.0],
            "p95": [123.5, 126.9, 130.1, 133.5, 137.1, 140.7, 144.3, 148.1, 152.0, 156.1, 160.5, 164.7, 168.7]
        }
        
        # CDC data for girls 6-12 years (weight in kg)
        self.cdc_weight_data = {
            "age": [6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0],
            "p5": [16.9, 17.7, 18.6, 19.5, 20.6, 21.6, 22.8, 24.0, 25.3, 26.7, 28.2, 29.9, 31.8],
            "p10": [17.6, 18.5, 19.5, 20.5, 21.6, 22.8, 24.0, 25.3, 26.7, 28.2, 29.9, 31.7, 33.7],
            "p25": [19.0, 20.0, 21.1, 22.3, 23.5, 24.8, 26.2, 27.7, 29.3, 31.0, 33.0, 35.1, 37.4],
            "p50": [20.7, 21.9, 23.3, 24.6, 26.0, 27.6, 29.3, 31.2, 33.1, 35.3, 37.5, 40.0, 42.6],
            "p75": [23.0, 24.4, 26.0, 27.6, 29.5, 31.4, 33.5, 35.8, 38.2, 40.7, 43.3, 46.0, 49.0],
            "p90": [25.8, 27.5, 29.5, 31.5, 33.8, 36.2, 38.9, 41.7, 44.7, 47.7, 50.8, 54.0, 57.4],
            "p95": [27.8, 29.8, 32.0, 34.3, 36.9, 39.7, 42.6, 45.8, 49.0, 52.2, 55.6, 59.0, 62.7]
        }
        
        # Convert to DataFrames for easier handling
        self.cdc_height_df = pd.DataFrame(self.cdc_height_data)
        self.cdc_weight_df = pd.DataFrame(self.cdc_weight_data)
        
        # Initialize measurements dataframe
        self.measurements = pd.DataFrame(columns=['date', 'age', 'height', 'weight'])
        
        # Sample data for demonstration
        sample_data = {
            'date': ['2022-05-26', '2023-06-01', '2024-04-22', '2025-04-22', '2025-12-01'],
            'age': [7.22, 8.24, 9.13, 10.13, 10.75],
            'height': [124.7, 131.1, 136, 141.8, 145.5],
            'weight': [23.5, 26.5, 27.8, 33.7, 36]
        }
        self.add_measurements_from_dict(sample_data)
    
    def add_measurement(self, date, age, height, weight):
        """Add a single measurement"""
        new_measurement = pd.DataFrame({
            'date': [date],
            'age': [float(age)],
            'height': [float(height)],
            'weight': [float(weight)]
        })
        self.measurements = pd.concat([self.measurements, new_measurement], ignore_index=True)
    
    def add_measurements_from_dict(self, data_dict):
        """Add multiple measurements from a dictionary"""
        new_measurements = pd.DataFrame(data_dict)
        self.measurements = pd.concat([self.measurements, new_measurements], ignore_index=True)
        
    def get_percentile_info(self, age, value, measurement_type):
        """Determine which percentile range a measurement falls into"""
        if measurement_type == 'height':
            data = self.cdc_height_df
        else:  # weight
            data = self.cdc_weight_df
        
        # Find closest age in data
        closest_age_idx = (data['age'] - age).abs().idxmin()
        age_data = data.iloc[closest_age_idx]
        
        if value < age_data['p5']:
            return "Below 5th percentile"
        elif value < age_data['p10']:
            return "Between 5th-10th percentile"
        elif value < age_data['p25']:
            return "Between 10th-25th percentile"
        elif value < age_data['p50']:
            return "Between 25th-50th percentile"
        elif value < age_data['p75']:
            return "Between 50th-75th percentile"
        elif value < age_data['p90']:
            return "Between 75th-90th percentile"
        elif value < age_data['p95']:
            return "Between 90th-95th percentile"
        else:
            return "Above 95th percentile"
    
    def plot_growth_chart(self, chart_type='height', figsize=(10, 8), save_path=None):
        """Plot the growth chart with the child's measurements"""
        plt.figure(figsize=figsize)
        
        # Choose appropriate data based on chart type
        if chart_type == 'height':
            cdc_data = self.cdc_height_df
            y_label = 'Height (cm)'
            measurement_values = self.measurements['height']
            y_min, y_max = 105, 170
            title = 'CDC Height-for-Age Growth Chart (Girls 6-12 years)'
        else:  # weight
            cdc_data = self.cdc_weight_df
            y_label = 'Weight (kg)'
            measurement_values = self.measurements['weight']
            y_min, y_max = 15, 75
            title = 'CDC Weight-for-Age Growth Chart (Girls 6-12 years)'
        
        # Plot percentile curves
        percentiles = ['p5', 'p10', 'p25', 'p50', 'p75', 'p90', 'p95']
        percentile_labels = ['5th', '10th', '25th', '50th', '75th', '90th', '95th']
        
        # Define colors for different percentile lines
        colors = {
            'p5': '#82ca9d',   # green
            'p10': '#8dd1e1',  # light blue
            'p25': '#82ca9d',  # green
            'p50': '#8884d8',  # purple
            'p75': '#82ca9d',  # green
            'p90': '#8dd1e1',  # light blue
            'p95': '#82ca9d',   # green
        }
        
        linewidths = {p: 2 if p == 'p50' else 1 for p in percentiles}
        
        # Plot percentile curves
        for percentile in percentiles:
            plt.plot(cdc_data['age'], cdc_data[percentile], 
                     label=f"{percentile.replace('p', '')}th percentile", 
                     color=colors[percentile], linewidth=linewidths[percentile])
        
        # Plot child's measurements as scatter points
        plt.scatter(self.measurements['age'], measurement_values, 
                   color='red', s=50, zorder=5, label="Your child")
        
        # Connect the dots chronologically
        plt.plot(self.measurements['age'], measurement_values, 
                color='red', linestyle='--', alpha=0.7, zorder=4)
        
        # Add data labels to the points
        for i, row in self.measurements.iterrows():
            plt.annotate(f"{row[chart_type]:.1f}",
                        (row['age'], row[chart_type]),
                        textcoords="offset points",
                        xytext=(0, 10),
                        ha='center')
        
        # Set axis limits and labels
        plt.xlim(6, 12)
        plt.ylim(y_min, y_max)
        plt.xlabel('Age (years)')
        plt.ylabel(y_label)
        plt.title(title)
        
        # Add grid for easier reading
        plt.grid(True, linestyle='--', alpha=0.7)
        
        # Adjust x-axis ticks
        plt.xticks(np.arange(6, 12, 0.5))
        
        # Create legend
        plt.legend(loc='upper left')
        
        # Add text with child's percentile info for the latest measurement
        if not self.measurements.empty:
            latest = self.measurements.iloc[-1]
            latest_age = latest['age']
            latest_value = latest[chart_type]
            percentile_info = self.get_percentile_info(latest_age, latest_value, chart_type)
            
            plt.figtext(0.5, 0.01, 
                      f"Latest measurement ({latest['date']}): {latest_value:.1f} {y_label.split(' ')[0]} "
                      f"at age {latest_age} years - {percentile_info}",
                      ha='center', fontsize=10, bbox=dict(facecolor='whitesmoke', alpha=0.5))
        
        plt.tight_layout()
        
        # Save the figure if path is provided
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Chart saved to {save_path}")
        
        plt.show()
        
    def print_measurements_table(self):
        """Print a table of all measurements with percentile information"""
        if self.measurements.empty:
            print("No measurements recorded.")
            return
            
        # Create a copy with calculated percentiles
        table_df = self.measurements.copy()
        table_df['height_percentile'] = table_df.apply(
            lambda row: self.get_percentile_info(row['age'], row['height'], 'height'), axis=1)
        table_df['weight_percentile'] = table_df.apply(
            lambda row: self.get_percentile_info(row['age'], row['weight'], 'weight'), axis=1)
        
        # Format the table
        print("\nMeasurements Table:")
        print("-" * 100)
        print(f"{'Date':<12} | {'Age (years)':<12} | {'Height (cm)':<12} | {'Height Percentile':<20} | {'Weight (kg)':<12} | {'Weight Percentile':<20}")
        print("-" * 100)
        
        for _, row in table_df.iterrows():
            print(f"{row['date']:<12} | {row['age']:<12.2f} | {row['height']:<12.1f} | {row['height_percentile']:<20} | {row['weight']:<12.1f} | {row['weight_percentile']:<20}")


# Example usage
if __name__ == "__main__":
    # Create plotter with sample data
    plotter = CDCGrowthChartPlotter()
    
    # Add additional measurements if needed
    # plotter.add_measurement('2025-11-15', 9.5, 138.5, 34.0)
    
    # Print table of all measurements
    plotter.print_measurements_table()
    
    # Plot height chart
    plotter.plot_growth_chart(chart_type='height')
    
    # Plot weight chart
    plotter.plot_growth_chart(chart_type='weight')
    
    # Example: Save charts to files
    # plotter.plot_growth_chart(chart_type='height', save_path='height_chart.png')
    # plotter.plot_growth_chart(chart_type='weight', save_path='weight_chart.png')