// generated from rosidl_generator_cpp/resource/idl__struct.hpp.em
// with input from bird_deterrent_vineyard_msgs:msg/Task.idl
// generated code does not contain a copyright notice

#ifndef BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__STRUCT_HPP_
#define BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__STRUCT_HPP_

#include <algorithm>
#include <array>
#include <memory>
#include <string>
#include <vector>

#include "rosidl_runtime_cpp/bounded_vector.hpp"
#include "rosidl_runtime_cpp/message_initialization.hpp"


#ifndef _WIN32
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__Task __attribute__((deprecated))
#else
# define DEPRECATED__bird_deterrent_vineyard_msgs__msg__Task __declspec(deprecated)
#endif

namespace bird_deterrent_vineyard_msgs
{

namespace msg
{

// message struct
template<class ContainerAllocator>
struct Task_
{
  using Type = Task_<ContainerAllocator>;

  explicit Task_(rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->id = "";
      this->type = "";
      this->x = 0.0;
      this->y = 0.0;
      this->time = 0.0;
      this->assigned_primary = "";
      this->assigned_secondary = "";
      this->score = 0.0f;
    }
  }

  explicit Task_(const ContainerAllocator & _alloc, rosidl_runtime_cpp::MessageInitialization _init = rosidl_runtime_cpp::MessageInitialization::ALL)
  : id(_alloc),
    type(_alloc),
    assigned_primary(_alloc),
    assigned_secondary(_alloc)
  {
    if (rosidl_runtime_cpp::MessageInitialization::ALL == _init ||
      rosidl_runtime_cpp::MessageInitialization::ZERO == _init)
    {
      this->id = "";
      this->type = "";
      this->x = 0.0;
      this->y = 0.0;
      this->time = 0.0;
      this->assigned_primary = "";
      this->assigned_secondary = "";
      this->score = 0.0f;
    }
  }

  // field types and members
  using _id_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _id_type id;
  using _type_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _type_type type;
  using _x_type =
    double;
  _x_type x;
  using _y_type =
    double;
  _y_type y;
  using _time_type =
    double;
  _time_type time;
  using _assigned_primary_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _assigned_primary_type assigned_primary;
  using _assigned_secondary_type =
    std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>>;
  _assigned_secondary_type assigned_secondary;
  using _score_type =
    float;
  _score_type score;

  // setters for named parameter idiom
  Type & set__id(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->id = _arg;
    return *this;
  }
  Type & set__type(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->type = _arg;
    return *this;
  }
  Type & set__x(
    const double & _arg)
  {
    this->x = _arg;
    return *this;
  }
  Type & set__y(
    const double & _arg)
  {
    this->y = _arg;
    return *this;
  }
  Type & set__time(
    const double & _arg)
  {
    this->time = _arg;
    return *this;
  }
  Type & set__assigned_primary(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->assigned_primary = _arg;
    return *this;
  }
  Type & set__assigned_secondary(
    const std::basic_string<char, std::char_traits<char>, typename std::allocator_traits<ContainerAllocator>::template rebind_alloc<char>> & _arg)
  {
    this->assigned_secondary = _arg;
    return *this;
  }
  Type & set__score(
    const float & _arg)
  {
    this->score = _arg;
    return *this;
  }

  // constant declarations

  // pointer types
  using RawPtr =
    bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator> *;
  using ConstRawPtr =
    const bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator> *;
  using SharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator>>;
  using ConstSharedPtr =
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator> const>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator>>>
  using UniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator>, Deleter>;

  using UniquePtr = UniquePtrWithDeleter<>;

  template<typename Deleter = std::default_delete<
      bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator>>>
  using ConstUniquePtrWithDeleter =
    std::unique_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator> const, Deleter>;
  using ConstUniquePtr = ConstUniquePtrWithDeleter<>;

  using WeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator>>;
  using ConstWeakPtr =
    std::weak_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator> const>;

  // pointer types similar to ROS 1, use SharedPtr / ConstSharedPtr instead
  // NOTE: Can't use 'using' here because GNU C++ can't parse attributes properly
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__Task
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator>>
    Ptr;
  typedef DEPRECATED__bird_deterrent_vineyard_msgs__msg__Task
    std::shared_ptr<bird_deterrent_vineyard_msgs::msg::Task_<ContainerAllocator> const>
    ConstPtr;

  // comparison operators
  bool operator==(const Task_ & other) const
  {
    if (this->id != other.id) {
      return false;
    }
    if (this->type != other.type) {
      return false;
    }
    if (this->x != other.x) {
      return false;
    }
    if (this->y != other.y) {
      return false;
    }
    if (this->time != other.time) {
      return false;
    }
    if (this->assigned_primary != other.assigned_primary) {
      return false;
    }
    if (this->assigned_secondary != other.assigned_secondary) {
      return false;
    }
    if (this->score != other.score) {
      return false;
    }
    return true;
  }
  bool operator!=(const Task_ & other) const
  {
    return !this->operator==(other);
  }
};  // struct Task_

// alias to use template instance with default allocator
using Task =
  bird_deterrent_vineyard_msgs::msg::Task_<std::allocator<void>>;

// constant definitions

}  // namespace msg

}  // namespace bird_deterrent_vineyard_msgs

#endif  // BIRD_DETERRENT_VINEYARD_MSGS__MSG__DETAIL__TASK__STRUCT_HPP_
