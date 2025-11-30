import React, { useState, useEffect } from 'react';
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const COLORS = ['#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'];

const TravelPlans = () => {
  const [plans, setPlans] = useState([]);
  const [selectedPlan, setSelectedPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchTravelPlans();
  }, []);

  const fetchTravelPlans = async () => {
    try {
      setLoading(true);
      const response = await fetch('http://127.0.0.1:5000/api/travel-plans');
      const data = await response.json();
      if (data.success) {
        setPlans(data.plans || []);
      } else {
        setError(data.error || 'Failed to fetch travel plans');
      }
    } catch (err) {
      setError('Error fetching travel plans: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const formatMoney = (val, currency = 'USD') => {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: currency }).format(val || 0);
  };

  const parseBudgetFromPlan = (plan) => {
    // 尝试从 route_plan 和 restaurant_plan 中提取预算信息
    const routePlan = plan.route_plan || '';
    const restaurantPlan = plan.restaurant_plan || '';
    
    // 改进的预算提取逻辑
    const routeCosts = [];
    const restaurantCosts = [];
    
    // 从 route_plan 中提取价格（支持多种格式：$100, $100.50, 100 USD, etc.）
    const routePricePatterns = [
      /\$(\d+(?:,\d{3})*(?:\.\d{2})?)/g,  // $100, $1,000, $100.50
      /(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:USD|dollars?|usd)/gi,  // 100 USD, 1000 dollars
      /cost[:\s]+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)/gi,  // cost: $100
      /price[:\s]+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)/gi,  // price: $100
      /total[:\s]+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)/gi,  // total: $100
    ];
    
    routePricePatterns.forEach(pattern => {
      const matches = routePlan.matchAll(pattern);
      for (const match of matches) {
        const priceStr = match[1].replace(/,/g, '');
        const price = parseFloat(priceStr);
        if (!isNaN(price) && price > 0 && price < 1000000) {  // 合理的价格范围
          routeCosts.push(price);
        }
      }
    });
    
    // 从 restaurant_plan 中提取价格
    routePricePatterns.forEach(pattern => {
      const matches = restaurantPlan.matchAll(pattern);
      for (const match of matches) {
        const priceStr = match[1].replace(/,/g, '');
        const price = parseFloat(priceStr);
        if (!isNaN(price) && price > 0 && price < 1000000) {  // 合理的价格范围
          restaurantCosts.push(price);
        }
      }
    });
    
    // 计算总成本（如果提取到多个价格，取平均值或总和，这里使用总和）
    // 但为了避免重复计算，我们可以尝试提取总成本
    let totalRouteCost = routeCosts.reduce((sum, cost) => sum + cost, 0);
    let totalRestaurantCost = restaurantCosts.reduce((sum, cost) => sum + cost, 0);
    
    // 如果提取到的价格太多，可能是重复计算，尝试查找总成本
    if (routeCosts.length > 20) {
      const totalMatch = routePlan.match(/total[:\s]+(?:cost|price|amount)[:\s]+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)/i);
      if (totalMatch) {
        totalRouteCost = parseFloat(totalMatch[1].replace(/,/g, ''));
      } else {
        // 如果价格太多，只取前几个较大的值
        const sortedCosts = routeCosts.sort((a, b) => b - a);
        totalRouteCost = sortedCosts.slice(0, 10).reduce((sum, cost) => sum + cost, 0);
      }
    }
    
    if (restaurantCosts.length > 20) {
      const totalMatch = restaurantPlan.match(/total[:\s]+(?:cost|price|amount)[:\s]+\$?(\d+(?:,\d{3})*(?:\.\d{2})?)/i);
      if (totalMatch) {
        totalRestaurantCost = parseFloat(totalMatch[1].replace(/,/g, ''));
      } else {
        const sortedCosts = restaurantCosts.sort((a, b) => b - a);
        totalRestaurantCost = sortedCosts.slice(0, 10).reduce((sum, cost) => sum + cost, 0);
      }
    }
    
    const totalEstimatedCost = totalRouteCost + totalRestaurantCost;
    const budget = plan.budget || 0;
    const remaining = budget - totalEstimatedCost;
    
    return {
      budget,
      totalRouteCost,
      totalRestaurantCost,
      totalEstimatedCost,
      remaining,
      routeCosts,
      restaurantCosts
    };
  };

  const renderPlanDetail = (plan) => {
    if (!plan) return null;

    const budgetData = parseBudgetFromPlan(plan);
    
    // 准备图表数据
    const pieData = [
      { name: 'Route Costs', value: budgetData.totalRouteCost },
      { name: 'Restaurant Costs', value: budgetData.totalRestaurantCost },
    ].filter(item => item.value > 0);

    const barData = [
      { name: 'Budget', value: budgetData.budget },
      { name: 'Estimated Cost', value: budgetData.totalEstimatedCost },
      { name: 'Remaining', value: Math.max(0, budgetData.remaining) },
    ];

    return (
      <div className="bg-white rounded-xl shadow-lg p-6 border border-stone-100 space-y-6">
        <div className="flex items-center justify-between border-b pb-4">
          <div>
            <h3 className="text-2xl font-bold text-indigo-900">{plan.destination || 'Travel Plan'}</h3>
            <p className="text-sm text-stone-500 mt-1">
              {plan.days ? `${plan.days} days` : ''} • Created: {new Date(plan.created_at).toLocaleDateString()}
            </p>
          </div>
          <button
            onClick={() => setSelectedPlan(null)}
            className="text-stone-400 hover:text-stone-600 transition-colors"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>

        {/* Budget Overview */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-indigo-50 p-4 rounded-lg border border-indigo-100">
            <p className="text-sm text-indigo-600 font-medium">Budget</p>
            <p className="text-2xl font-bold text-indigo-900">{formatMoney(budgetData.budget, plan.currency)}</p>
          </div>
          <div className="bg-stone-50 p-4 rounded-lg border border-stone-100">
            <p className="text-sm text-stone-600 font-medium">Estimated Cost</p>
            <p className="text-2xl font-bold text-stone-900">{formatMoney(budgetData.totalEstimatedCost, plan.currency)}</p>
          </div>
          <div className={`p-4 rounded-lg border ${
            budgetData.remaining >= 0 
              ? 'bg-green-50 border-green-100' 
              : 'bg-red-50 border-red-100'
          }`}>
            <p className={`text-sm font-medium ${
              budgetData.remaining >= 0 ? 'text-green-600' : 'text-red-600'
            }`}>
              {budgetData.remaining >= 0 ? 'Remaining' : 'Over Budget'}
            </p>
            <p className={`text-2xl font-bold ${
              budgetData.remaining >= 0 ? 'text-green-900' : 'text-red-900'
            }`}>
              {formatMoney(Math.abs(budgetData.remaining), plan.currency)}
            </p>
          </div>
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Pie Chart - Cost Breakdown */}
          {pieData.length > 0 && (
            <div className="bg-stone-50 p-4 rounded-lg border border-stone-200">
              <h4 className="text-lg font-bold text-stone-800 mb-4">Cost Breakdown</h4>
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value) => formatMoney(value, plan.currency)} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Bar Chart - Budget vs Cost */}
          <div className="bg-stone-50 p-4 rounded-lg border border-stone-200">
            <h4 className="text-lg font-bold text-stone-800 mb-4">Budget Comparison</h4>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={barData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip formatter={(value) => formatMoney(value, plan.currency)} />
                <Legend />
                <Bar dataKey="value" fill="#4f46e5" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Plan Details */}
        <div className="space-y-4">
          <div>
            <h4 className="text-lg font-bold text-stone-800 mb-2">Route Plan</h4>
            <div className="bg-stone-50 p-4 rounded-lg border border-stone-200 max-h-64 overflow-y-auto">
              <pre className="whitespace-pre-wrap text-sm text-stone-700 font-sans">
                {plan.route_plan || 'No route plan available.'}
              </pre>
            </div>
          </div>

          {plan.restaurant_plan && (
            <div>
              <h4 className="text-lg font-bold text-stone-800 mb-2">Restaurant Plan</h4>
              <div className="bg-stone-50 p-4 rounded-lg border border-stone-200 max-h-64 overflow-y-auto">
                <pre className="whitespace-pre-wrap text-sm text-stone-700 font-sans">
                  {plan.restaurant_plan}
                </pre>
              </div>
            </div>
          )}

          {plan.participants && plan.participants.length > 0 && (
            <div>
              <h4 className="text-lg font-bold text-stone-800 mb-2">Participants</h4>
              <div className="flex flex-wrap gap-2">
                {plan.participants.map((participant, idx) => (
                  <span
                    key={idx}
                    className="px-3 py-1 bg-indigo-100 text-indigo-700 rounded-full text-sm font-medium"
                  >
                    {participant}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-indigo-600 mx-auto mb-4"></div>
          <p className="text-stone-600">Loading travel plans...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center bg-red-50 border border-red-200 rounded-lg p-6 max-w-md">
          <p className="text-red-600 font-medium">Error</p>
          <p className="text-red-500 text-sm mt-2">{error}</p>
          <button
            onClick={fetchTravelPlans}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (selectedPlan) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        {renderPlanDetail(selectedPlan)}
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      <div className="mb-8">
        <h2 className="text-3xl font-serif font-bold text-indigo-900 mb-2">Travel Plans</h2>
        <p className="text-stone-500">View and manage your saved travel plans</p>
      </div>

      {plans.length === 0 ? (
        <div className="text-center py-20 bg-white rounded-xl border border-dashed border-stone-300">
          <svg className="w-16 h-16 text-stone-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
          </svg>
          <p className="text-xl text-stone-600 font-medium">No travel plans yet</p>
          <p className="text-stone-400 text-sm mt-2">Travel plans will appear here after you confirm them in the chat.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {plans.map((plan) => (
            <div
              key={plan.id}
              onClick={() => setSelectedPlan(plan)}
              className="bg-white rounded-xl shadow-md border border-stone-200 p-6 cursor-pointer hover:shadow-lg transition-all hover:border-indigo-300"
            >
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h3 className="text-xl font-bold text-indigo-900">{plan.destination || 'Travel Plan'}</h3>
                  <p className="text-sm text-stone-500 mt-1">
                    {plan.days ? `${plan.days} days` : 'No duration specified'}
                  </p>
                </div>
                <div className="bg-indigo-100 text-indigo-700 px-2 py-1 rounded text-xs font-medium">
                  #{plan.id}
                </div>
              </div>

              <div className="space-y-2 mb-4">
                <div className="flex justify-between text-sm">
                  <span className="text-stone-600">Budget:</span>
                  <span className="font-bold text-indigo-900">
                    {formatMoney(plan.budget, plan.currency)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-stone-600">Created:</span>
                  <span className="text-stone-700">
                    {new Date(plan.created_at).toLocaleDateString()}
                  </span>
                </div>
                {plan.participants && plan.participants.length > 0 && (
                  <div className="flex justify-between text-sm">
                    <span className="text-stone-600">Participants:</span>
                    <span className="text-stone-700">{plan.participants.length}</span>
                  </div>
                )}
              </div>

              <div className="pt-4 border-t border-stone-200">
                <button className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors text-sm font-medium">
                  View Details
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default TravelPlans;

