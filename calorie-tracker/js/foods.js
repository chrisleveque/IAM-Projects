/*
 * foods.js — built-in food database.
 *
 * All values are per 100 g (edible portion): kcal, protein (g), carbs (g),
 * fat (g). Figures are rounded reference values derived from USDA FoodData
 * Central (https://fdc.nal.usda.gov/), a U.S. government work in the public
 * domain. They are typical values for the named food, not for any brand.
 */
"use strict";

const BUILTIN_FOODS = [
  // Fruits
  { id: "apple", name: "Apple (raw, with skin)", kcal: 52, protein: 0.3, carbs: 13.8, fat: 0.2 },
  { id: "banana", name: "Banana (raw)", kcal: 89, protein: 1.1, carbs: 22.8, fat: 0.3 },
  { id: "orange", name: "Orange (raw)", kcal: 47, protein: 0.9, carbs: 11.8, fat: 0.1 },
  { id: "strawberries", name: "Strawberries (raw)", kcal: 32, protein: 0.7, carbs: 7.7, fat: 0.3 },
  { id: "blueberries", name: "Blueberries (raw)", kcal: 57, protein: 0.7, carbs: 14.5, fat: 0.3 },
  { id: "grapes", name: "Grapes (raw)", kcal: 69, protein: 0.7, carbs: 18.1, fat: 0.2 },
  { id: "avocado", name: "Avocado (raw)", kcal: 160, protein: 2.0, carbs: 8.5, fat: 14.7 },

  // Vegetables
  { id: "broccoli", name: "Broccoli (cooked)", kcal: 35, protein: 2.4, carbs: 7.2, fat: 0.4 },
  { id: "carrot", name: "Carrot (raw)", kcal: 41, protein: 0.9, carbs: 9.6, fat: 0.2 },
  { id: "spinach", name: "Spinach (raw)", kcal: 23, protein: 2.9, carbs: 3.6, fat: 0.4 },
  { id: "tomato", name: "Tomato (raw)", kcal: 18, protein: 0.9, carbs: 3.9, fat: 0.2 },
  { id: "potato_baked", name: "Potato (baked, with skin)", kcal: 93, protein: 2.5, carbs: 21.2, fat: 0.1 },
  { id: "sweet_potato", name: "Sweet potato (baked)", kcal: 90, protein: 2.0, carbs: 20.7, fat: 0.2 },
  { id: "cucumber", name: "Cucumber (raw)", kcal: 15, protein: 0.7, carbs: 3.6, fat: 0.1 },
  { id: "lettuce", name: "Lettuce (romaine, raw)", kcal: 17, protein: 1.2, carbs: 3.3, fat: 0.3 },

  // Grains & starches
  { id: "rice_white", name: "White rice (cooked)", kcal: 130, protein: 2.7, carbs: 28.2, fat: 0.3 },
  { id: "rice_brown", name: "Brown rice (cooked)", kcal: 123, protein: 2.7, carbs: 25.6, fat: 1.0 },
  { id: "pasta", name: "Pasta (cooked)", kcal: 158, protein: 5.8, carbs: 30.9, fat: 0.9 },
  { id: "bread_white", name: "White bread", kcal: 266, protein: 8.9, carbs: 49.4, fat: 3.3 },
  { id: "bread_whole", name: "Whole-wheat bread", kcal: 247, protein: 13.0, carbs: 41.3, fat: 3.4 },
  { id: "oats", name: "Oatmeal (cooked with water)", kcal: 71, protein: 2.5, carbs: 12.0, fat: 1.5 },
  { id: "quinoa", name: "Quinoa (cooked)", kcal: 120, protein: 4.4, carbs: 21.3, fat: 1.9 },
  { id: "tortilla", name: "Flour tortilla", kcal: 306, protein: 8.2, carbs: 50.4, fat: 7.8 },

  // Protein
  { id: "chicken_breast", name: "Chicken breast (roasted, skinless)", kcal: 165, protein: 31.0, carbs: 0.0, fat: 3.6 },
  { id: "chicken_thigh", name: "Chicken thigh (roasted, skinless)", kcal: 209, protein: 26.0, carbs: 0.0, fat: 10.9 },
  { id: "beef_ground", name: "Ground beef (85% lean, cooked)", kcal: 250, protein: 25.9, carbs: 0.0, fat: 15.4 },
  { id: "steak", name: "Beef sirloin steak (grilled)", kcal: 212, protein: 29.0, carbs: 0.0, fat: 9.9 },
  { id: "pork_chop", name: "Pork chop (grilled)", kcal: 231, protein: 27.3, carbs: 0.0, fat: 12.8 },
  { id: "salmon", name: "Salmon (baked)", kcal: 206, protein: 22.1, carbs: 0.0, fat: 12.4 },
  { id: "tuna_canned", name: "Tuna (canned in water, drained)", kcal: 116, protein: 25.5, carbs: 0.0, fat: 0.8 },
  { id: "shrimp", name: "Shrimp (cooked)", kcal: 99, protein: 24.0, carbs: 0.2, fat: 0.3 },
  { id: "egg", name: "Egg (whole, cooked)", kcal: 155, protein: 12.6, carbs: 1.1, fat: 10.6 },
  { id: "tofu", name: "Tofu (firm)", kcal: 78, protein: 9.0, carbs: 2.3, fat: 4.2 },
  { id: "beans_black", name: "Black beans (cooked)", kcal: 132, protein: 8.9, carbs: 23.7, fat: 0.5 },
  { id: "chickpeas", name: "Chickpeas (cooked)", kcal: 164, protein: 8.9, carbs: 27.4, fat: 2.6 },
  { id: "lentils", name: "Lentils (cooked)", kcal: 116, protein: 9.0, carbs: 20.1, fat: 0.4 },

  // Dairy
  { id: "milk_whole", name: "Milk (whole)", kcal: 61, protein: 3.2, carbs: 4.8, fat: 3.3 },
  { id: "milk_skim", name: "Milk (skim)", kcal: 34, protein: 3.4, carbs: 5.0, fat: 0.1 },
  { id: "yogurt_greek", name: "Greek yogurt (plain, nonfat)", kcal: 59, protein: 10.2, carbs: 3.6, fat: 0.4 },
  { id: "cheese_cheddar", name: "Cheddar cheese", kcal: 403, protein: 24.9, carbs: 1.3, fat: 33.1 },
  { id: "cottage_cheese", name: "Cottage cheese (2%)", kcal: 84, protein: 11.0, carbs: 4.3, fat: 2.3 },
  { id: "butter", name: "Butter", kcal: 717, protein: 0.9, carbs: 0.1, fat: 81.1 },

  // Nuts, oils & snacks
  { id: "almonds", name: "Almonds (raw)", kcal: 579, protein: 21.2, carbs: 21.6, fat: 49.9 },
  { id: "peanut_butter", name: "Peanut butter (smooth)", kcal: 588, protein: 25.1, carbs: 19.6, fat: 50.4 },
  { id: "walnuts", name: "Walnuts", kcal: 654, protein: 15.2, carbs: 13.7, fat: 65.2 },
  { id: "olive_oil", name: "Olive oil", kcal: 884, protein: 0.0, carbs: 0.0, fat: 100.0 },
  { id: "dark_chocolate", name: "Dark chocolate (70–85% cacao)", kcal: 598, protein: 7.8, carbs: 45.9, fat: 42.6 },
  { id: "potato_chips", name: "Potato chips (plain, salted)", kcal: 536, protein: 7.0, carbs: 52.9, fat: 34.6 },
  { id: "popcorn", name: "Popcorn (air-popped)", kcal: 387, protein: 12.9, carbs: 77.8, fat: 4.5 },

  // Prepared / common meals
  { id: "pizza_cheese", name: "Cheese pizza (regular crust)", kcal: 266, protein: 11.4, carbs: 33.3, fat: 9.7 },
  { id: "hamburger", name: "Hamburger (single patty, with bun)", kcal: 254, protein: 12.3, carbs: 27.3, fat: 10.5 },
  { id: "french_fries", name: "French fries", kcal: 312, protein: 3.4, carbs: 41.4, fat: 15.0 },
  { id: "soup_chicken_noodle", name: "Chicken noodle soup", kcal: 36, protein: 1.9, carbs: 4.5, fat: 1.1 },
  { id: "protein_shake", name: "Whey protein powder", kcal: 375, protein: 75.0, carbs: 12.5, fat: 5.0 },
];

if (typeof module !== "undefined" && module.exports) {
  module.exports = BUILTIN_FOODS;
} else {
  window.BUILTIN_FOODS = BUILTIN_FOODS;
}
