// generated from rosidl_generator_cpp/resource/idl__traits.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Zone.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__TRAITS_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__TRAITS_HPP_

#include <stdint.h>

#include <sstream>
#include <string>
#include <type_traits>

#include "bird_deterrent_vineyard_msgs/msg/detail/zone__struct.hpp"
#include "rosidl_runtime_cpp/traits.hpp"

// Include directives for member types
// Member 'polygon'
#include "bird_deterrent_vineyard_msgs/msg/detail/polygon2_d__traits.hpp"

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

inline void to_flow_style_yaml(
  const Zone & msg,
  std::ostream & out)
{
  out << "{";
  // member: robot_id
  {
    out << "robot_id: ";
    rosidl_generator_traits::value_to_yaml(msg.robot_id, out);
    out << ", ";
  }

  // member: polygon
  {
    out << "polygon: ";
    to_flow_style_yaml(msg.polygon, out);
    out << ", ";
  }

  // member: neighbors
  {
    if (msg.neighbors.size() == 0) {
      out << "neighbors: []";
    } else {
      out << "neighbors: [";
      size_t pending_items = msg.neighbors.size();
      for (auto item : msg.neighbors) {
        rosidl_generator_traits::value_to_yaml(item, out);
        if (--pending_items > 0) {
          out << ", ";
        }
      }
      out << "]";
    }
  }
  out << "}";
}  // NOLINT(readability/fn_size)

inline void to_block_style_yaml(
  const Zone & msg,
  std::ostream & out, size_t indentation = 0)
{
  // member: robot_id
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "robot_id: ";
    rosidl_generator_traits::value_to_yaml(msg.robot_id, out);
    out << "\n";
  }

  // member: polygon
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    out << "polygon:\n";
    to_block_style_yaml(msg.polygon, out, indentation + 2);
  }

  // member: neighbors
  {
    if (indentation > 0) {
      out << std::string(indentation, ' ');
    }
    if (msg.neighbors.size() == 0) {
      out << "neighbors: []\n";
    } else {
      out << "neighbors:\n";
      for (auto item : msg.neighbors) {
        if (indentation > 0) {
          out << std::string(indentation, ' ');
        }
        out << "- ";
        rosidl_generator_traits::value_to_yaml(item, out);
        out << "\n";
      }
    }
  }
}  // NOLINT(readability/fn_size)

inline std::string to_yaml(const Zone & msg, bool use_flow_style = false)
{
  std::ostringstream out;
  if (use_flow_style) {
    to_flow_style_yaml(msg, out);
  } else {
    to_block_style_yaml(msg, out);
  }
  return out.str();
}

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

namespace rosidl_generator_traits
{

[[deprecated("use bird_deterrent_vineyard_msgs::msg::to_block_style_yaml() instead")]]
inline void to_yaml(
  const bird_deterrent_vineyard_msgs::msg::Zone & msg,
  std::ostream & out, size_t indentation = 0)
{
  bird_deterrent_vineyard_msgs::msg::to_block_style_yaml(msg, out, indentation);
}

[[deprecated("use bird_deterrent_vineyard_msgs::msg::to_yaml() instead")]]
inline std::string to_yaml(const bird_deterrent_vineyard_msgs::msg::Zone & msg)
{
  return bird_deterrent_vineyard_msgs::msg::to_yaml(msg);
}

template<>
inline const char * data_type<bird_deterrent_vineyard_msgs::msg::Zone>()
{
  return "bird_deterrent_vineyard_msgs::msg::Zone";
}

template<>
inline const char * name<bird_deterrent_vineyard_msgs::msg::Zone>()
{
  return "bird_deterrent_vineyard_msgs/msg/Zone";
}

template<>
struct has_fixed_size<bird_deterrent_vineyard_msgs::msg::Zone>
  : std::integral_constant<bool, false> {};

template<>
struct has_bounded_size<bird_deterrent_vineyard_msgs::msg::Zone>
  : std::integral_constant<bool, false> {};

template<>
struct is_message<bird_deterrent_vineyard_msgs::msg::Zone>
  : std::true_type {};

}  // namespace rosidl_generator_traits

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__ZONE__TRAITS_HPP_
