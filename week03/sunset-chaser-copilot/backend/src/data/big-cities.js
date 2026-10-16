/**
 * The fallback roster, per spec step 3: "always provide at least a few cameras
 * that are located in 'day-time-zone' in big cities".
 *
 * This exists because the terminator is usually over water. A full sunset arc is
 * 20,015 km long and roughly 70% of it crosses open ocean at any moment, so on a
 * bad sample the primary list can legitimately come back thin. These cities are
 * the guarantee that the app always has something to show.
 *
 * `population` is metro population in millions, used only to rank which cities
 * to query first when the call budget cannot cover them all. The longitudes are
 * spread deliberately: somewhere in this list is in daylight at every UTC hour,
 * including the Pacific gap that a Europe/Americas-heavy list would leave.
 */

export const BIG_CITIES = Object.freeze([
  // East Asia / Oceania - the daylight zone for UTC 20:00-08:00
  { name: 'Tokyo', country: 'Japan', lat: 35.6762, lon: 139.6503, population: 37.4 },
  { name: 'Seoul', country: 'South Korea', lat: 37.5665, lon: 126.978, population: 9.9 },
  { name: 'Shanghai', country: 'China', lat: 31.2304, lon: 121.4737, population: 27.8 },
  { name: 'Beijing', country: 'China', lat: 39.9042, lon: 116.4074, population: 21.5 },
  { name: 'Hong Kong', country: 'China', lat: 22.3193, lon: 114.1694, population: 7.5 },
  { name: 'Manila', country: 'Philippines', lat: 14.5995, lon: 120.9842, population: 13.9 },
  { name: 'Jakarta', country: 'Indonesia', lat: -6.2088, lon: 106.8456, population: 10.6 },
  { name: 'Singapore', country: 'Singapore', lat: 1.3521, lon: 103.8198, population: 5.9 },
  { name: 'Bangkok', country: 'Thailand', lat: 13.7563, lon: 100.5018, population: 10.5 },
  { name: 'Sydney', country: 'Australia', lat: -33.8688, lon: 151.2093, population: 5.3 },
  { name: 'Melbourne', country: 'Australia', lat: -37.8136, lon: 144.9631, population: 5.0 },
  { name: 'Auckland', country: 'New Zealand', lat: -36.8485, lon: 174.7633, population: 1.7 },

  // South and Central Asia / Middle East - daylight for UTC 02:00-14:00
  { name: 'Delhi', country: 'India', lat: 28.6139, lon: 77.209, population: 31.0 },
  { name: 'Mumbai', country: 'India', lat: 19.076, lon: 72.8777, population: 20.7 },
  { name: 'Dhaka', country: 'Bangladesh', lat: 23.8103, lon: 90.4125, population: 21.7 },
  { name: 'Karachi', country: 'Pakistan', lat: 24.8607, lon: 67.0011, population: 16.1 },
  { name: 'Dubai', country: 'United Arab Emirates', lat: 25.2048, lon: 55.2708, population: 3.5 },

  // Africa / Europe - daylight for UTC 05:00-18:00
  { name: 'Istanbul', country: 'Türkiye', lat: 41.0082, lon: 28.9784, population: 15.5 },
  { name: 'Moscow', country: 'Russia', lat: 55.7558, lon: 37.6173, population: 12.6 },
  { name: 'Cairo', country: 'Egypt', lat: 30.0444, lon: 31.2357, population: 21.3 },
  { name: 'Nairobi', country: 'Kenya', lat: -1.2921, lon: 36.8219, population: 4.4 },
  { name: 'Lagos', country: 'Nigeria', lat: 6.5244, lon: 3.3792, population: 15.4 },
  { name: 'Cape Town', country: 'South Africa', lat: -33.9249, lon: 18.4241, population: 4.6 },
  { name: 'Johannesburg', country: 'South Africa', lat: -26.2041, lon: 28.0473, population: 5.8 },
  { name: 'Paris', country: 'France', lat: 48.8566, lon: 2.3522, population: 11.1 },
  { name: 'London', country: 'United Kingdom', lat: 51.5074, lon: -0.1278, population: 9.5 },
  { name: 'Berlin', country: 'Germany', lat: 52.52, lon: 13.405, population: 3.7 },
  { name: 'Madrid', country: 'Spain', lat: 40.4168, lon: -3.7038, population: 6.7 },
  { name: 'Rome', country: 'Italy', lat: 41.9028, lon: 12.4964, population: 2.9 },
  { name: 'Lisbon', country: 'Portugal', lat: 38.7223, lon: -9.1393, population: 2.9 },
  { name: 'Reykjavík', country: 'Iceland', lat: 64.1466, lon: -21.9426, population: 0.14 },

  // Americas - daylight for UTC 11:00-02:00
  { name: 'New York', country: 'United States', lat: 40.7128, lon: -74.006, population: 18.8 },
  { name: 'Chicago', country: 'United States', lat: 41.8781, lon: -87.6298, population: 8.9 },
  { name: 'Los Angeles', country: 'United States', lat: 34.0522, lon: -118.2437, population: 12.5 },
  { name: 'Mexico City', country: 'Mexico', lat: 19.4326, lon: -99.1332, population: 21.8 },
  { name: 'Toronto', country: 'Canada', lat: 43.6532, lon: -79.3832, population: 6.2 },
  { name: 'Vancouver', country: 'Canada', lat: 49.2827, lon: -123.1207, population: 2.6 },
  { name: 'São Paulo', country: 'Brazil', lat: -23.5505, lon: -46.6333, population: 22.4 },
  { name: 'Rio de Janeiro', country: 'Brazil', lat: -22.9068, lon: -43.1729, population: 13.5 },
  { name: 'Buenos Aires', country: 'Argentina', lat: -34.6037, lon: -58.3816, population: 15.2 },
  { name: 'Santiago', country: 'Chile', lat: -33.4489, lon: -70.6693, population: 6.8 },
  { name: 'Lima', country: 'Peru', lat: -12.0464, lon: -77.0428, population: 10.7 },

  // Pacific - fills the longitude gap where nothing else is in daylight
  { name: 'Honolulu', country: 'United States', lat: 21.3069, lon: -157.8583, population: 1.0 },
  { name: 'Anchorage', country: 'United States', lat: 61.2181, lon: -149.9003, population: 0.29 },
]);

export default BIG_CITIES;
